from __future__ import annotations

import asyncio
import hashlib
import json
import math
import os
import random
import re
import shutil
import tempfile
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlparse

import botpy
from PIL import Image as PILImage

from astrbot.api import logger
from astrbot.api.event import MessageChain
from astrbot.api.message_components import At, AtAll, Image, Node, Nodes, Plain, Reply
from astrbot.core.platform.astr_message_event import AstrMessageEvent
from astrbot.core.platform.sources.qqofficial.qqofficial_message_event import QQOfficialMessageEvent
from astrbot.core.platform.sources.qqofficial.qqofficial_platform_adapter import QQOfficialPlatformAdapter

from .menus import FAMILIES, buttons_for_event
from .button_actions import is_complete_callback
from .button_prompts import ButtonPromptStore
from .callback_actions import CallbackActionStore
from .keyboard_pages import HOME_BUTTON, MAX_BUTTONS, PAGE_HINT_KEY, KeyboardPageStore, unbound_keyboard
from .menu_receipts import MENU_RECEIPT_HINT_KEY, MenuReceiptStore
from .button_receipts import CLICKED_CARD_KEY, OUTGOING_BUTTONS_KEY, ButtonReceiptStore
from .support import get_card_hint
from .help_images import category_image_spec, text_help_title
from .menu_image import render_command_menu, render_text_menu


def is_progress_reply(components):
    """Keep the source card until an actual result, usage or error is delivered."""
    if any(not isinstance(c, (Plain, At, AtAll, Reply)) for c in components):
        return False
    text = '\n'.join(c.text for c in components if isinstance(c, Plain)).strip()
    if not text or len(text) > 1000:
        return False
    if re.search(r'失败|错误|超时|未完成|未执行|权限|不支持|未配置|不存在|异常|已停止|已取消', text):
        return False
    return bool(re.search(
        r'正在[^。\n]{0,20}(?:查询|搜索|检索|下载|解析|获取|生成|读取|处理|发送|加载|绑定|上传)'
        r'|开始(?:为你|帮你)?(?:下载|查询|搜索|解析)'
        r'|稍等|稍候|请(?:耐心)?等待|请勿重复(?:点击|调用)', text))


def is_pending_delivery(event, chain, components):
    if getattr(chain, 'qqofficial_pending', False):
        return True
    original = getattr(event, 'send_buffer', None)
    if (getattr(original, 'qqofficial_pending', False) and original.chain and chain.chain
            and chain.chain[-1] is original.chain[-1]):
        return True
    return is_progress_reply(components)


def flatten_components(components, depth=0):
    """Forward messages have no official equivalent; preserve their ordered bodies."""
    if depth > 12:
        raise ValueError("forward nesting exceeds supported depth")
    result = []
    for component in components:
        if isinstance(component, Nodes):
            result.extend(flatten_components(component.nodes, depth + 1))
        elif isinstance(component, Node):
            if result:
                result.append(Plain("\n\n"))
            result.extend(flatten_components(component.content, depth + 1))
        else:
            result.append(component)
    return result


def _safe_enter(command):
    safe = {b["command"] for _, _, buttons in FAMILIES.values() for b in buttons if b["enter"]}
    safe.update(f"/功能菜单 {name}" for name in FAMILIES)
    return command in safe or command == "/功能菜单" or is_complete_callback(command)


def normalize_buttons(value, *, navigation_commands=frozenset(), internal_enter_commands=frozenset(), _depth=0):
    if _depth > 8:
        return []
    result = []
    for item in value or []:
        if isinstance(item, list):
            result.extend(normalize_buttons(item, navigation_commands=navigation_commands,
                                            internal_enter_commands=internal_enter_commands, _depth=_depth + 1))
        elif isinstance(item, dict):
            # The upstream distinguishes callbacks (submit) from input helpers
            # (edit first). Preserve that intent through repeated normalization.
            editable = isinstance(item.get("input"), str) and bool(item["input"])
            command = item.get("input") if editable else (item.get("command") or item.get("callback"))
            requested_enter = not editable and bool(item.get("enter", bool(item.get("callback"))))
            label = item.get("label") or item.get("text")
            if isinstance(command, str) and isinstance(label, str) and command.strip():
                # Dynamic account/actions remain editable until the user submits them.
                result.append({"label": label[:40], "command": command[:512],
                               "enter": requested_enter and
                               (_safe_enter(command) or command in navigation_commands
                                or command in internal_enter_commands)})
        if len(result) >= MAX_BUTTONS:
            break
    return result[:MAX_BUTTONS]


def build_keyboard(buttons, *, navigation_commands=frozenset(), internal_enter_commands=frozenset(), callback_actions=None):
    buttons = normalize_buttons(buttons, navigation_commands=navigation_commands,
                                internal_enter_commands=internal_enter_commands)
    if len(buttons) > 10:
        raise ValueError("QQ two-column keyboards require pagination above ten buttons")
    rows = []
    action_buttons = [item for item in buttons if item["command"] not in navigation_commands]
    navigation_buttons = [item for item in buttons if item["command"] in navigation_commands]
    groups = [action_buttons[index:index + 2] for index in range(0, len(action_buttons), 2)]
    if navigation_buttons:
        groups.append(navigation_buttons)
    if len(groups) > 5 or any(len(group) > 2 for group in groups):
        raise ValueError("QQ two-column keyboards require at most five rows")
    button_id = 0
    for group in groups:
        row = []
        for item in group:
            button_id += 1
            action = (callback_actions or {}).get(item['command'])
            if callback_actions is not None and action is None:
                raise ValueError('callback action was not issued for this button')
            row.append({"id": str(button_id),
                        "render_data": {"label": item["label"], "visited_label": item["label"], "style": 0},
                        "action": action or {"type": 2, "permission": {"type": 2},
                                   "data": item["command"], "enter": item["enter"],
                                   "unsupport_tips": "请手动输入菜单中的命令"}})
        rows.append({"buttons": row})
    return {"content": {"rows": rows}} if rows else None


def explicit_rejection(error):
    """Only known API rejections are safe to resend; transport failures are ambiguous."""
    allowed = tuple(getattr(botpy.errors, name) for name in
                    ("ServerError", "ForbiddenError", "BadRequestError") if hasattr(botpy.errors, name))
    if not allowed or not isinstance(error, allowed):
        return None
    message = str(error).lower()
    rejected = any(word in message for word in (
        "not allow", "not support", "not permitted", "no permission", "forbidden", "invalid",
        "不允许", "未开通", "无权限", "不支持", "参数错误", "参数校验", "不合法"))
    if rejected and any(word in message for word in ("keyboard", "keyborad", "按钮")):
        return "keyboard"
    if rejected and any(word in message for word in ("markdown", "原生 md", "图片url", "image url")):
        return "markdown"
    return None


def require_receipt(response):
    if isinstance(response, dict):
        failed = response.get('status') == 'failed' or any(
            response.get(key) not in (None, 0, '0')
            for key in ('code', 'retcode', 'errcode')
        )
        message_id = None if failed else (response.get('id') or response.get('message_id'))
    else:
        message_id = getattr(response, 'id', None)
    valid = ((isinstance(message_id, str) and bool(message_id.strip()))
             or (type(message_id) is int and message_id != 0))
    if not valid:
        raise RuntimeError("QQ API returned no receipt; delivery is unconfirmed")
    return response


class ImagePublisher:
    """Reusable, expiring access only to images explicitly emitted by the bot.

    AstrBot's original token service consumes a token on first GET. Its original
    handler is used once at registration, then this instance owns that token.
    Other tokens retain the exact original behavior.
    """

    def __init__(self, service, cache_dir, public_base_url, ttl=21600, max_tokens=256,
                 max_image_bytes=32 * 1024 * 1024, max_cache_bytes=256 * 1024 * 1024):
        parsed = urlparse(public_base_url)
        if parsed.scheme != "https" or not parsed.netloc or parsed.query or parsed.fragment:
            raise ValueError("public_base_url must be an HTTPS base URL")
        self.service = service
        self.cache_dir = Path(cache_dir).resolve()
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.base_url = public_base_url.rstrip("/")
        self.ttl = max(60, min(int(ttl), 86400))
        self.max_tokens = max(8, min(int(max_tokens), 512))
        self.max_image_bytes = max(1024, min(int(max_image_bytes), 64 * 1024 * 1024))
        self.max_cache_bytes = max(self.max_image_bytes, min(int(max_cache_bytes), 512 * 1024 * 1024))
        self.publish_lock = asyncio.Lock()
        self.index_lock = threading.RLock()
        self.protected_paths = set()
        self.owned = {}
        self.index_path = self.cache_dir / "owned_image_tokens.json"
        self.original = getattr(service.handle_file, "_official_cards_original", service.handle_file)
        self.wrapper = None
        self._load_index()

    def _indexed_path(self, filename):
        if not isinstance(filename, str) or not re.fullmatch(r"[0-9a-f]{64}\.(?:png|jpg|gif|webp|bmp)", filename):
            return None
        path = self.cache_dir / filename
        if path.is_symlink() or path.resolve().parent != self.cache_dir or not path.is_file():
            return None
        return path

    def _load_index(self):
        # Persist only this publisher's capabilities, never the shared registry.
        if not self.index_path.exists() or self.index_path.is_symlink():
            return
        try:
            if self.index_path.stat().st_size > 512 * 1024:
                return
            os.chmod(self.index_path, 0o600)
            data = json.loads(self.index_path.read_text(encoding="utf-8"))
            if not isinstance(data, dict) or data.get("version") != 1 or not isinstance(data.get("tokens"), dict):
                return
            epoch_now, monotonic_now = time.time(), time.monotonic()
            candidates = []
            for token, entry in data["tokens"].items():
                if not isinstance(token, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,512}", token) or not isinstance(entry, dict):
                    continue
                expiry = entry.get("expires_at")
                if isinstance(expiry, bool) or not isinstance(expiry, (int, float)) or not math.isfinite(expiry):
                    continue
                remaining = min(expiry - epoch_now, self.ttl)
                path = self._indexed_path(entry.get("filename"))
                if remaining > 0 and path is not None:
                    candidates.append((token, path, monotonic_now + remaining))
            candidates.sort(key=lambda item: item[2], reverse=True)
            self.owned = {token: (path, expiry) for token, path, expiry in candidates[:self.max_tokens]}
            self.cleanup()
        except (OSError, ValueError, TypeError):
            logger.info("[OfficialCards] Image token index unavailable; existing external tokens are unchanged.")

    def _save_index(self):
        with self.index_lock:
            epoch_now, monotonic_now = time.time(), time.monotonic()
            tokens = {
                token: {"filename": path.name, "expires_at": epoch_now + expiry - monotonic_now}
                for token, (path, expiry) in self.owned.items()
                if expiry > monotonic_now and math.isfinite(expiry)
            }
            descriptor, temporary = tempfile.mkstemp(prefix=".owned_image_tokens-", suffix=".tmp", dir=self.index_path.parent)
            try:
                os.chmod(temporary, 0o600)
                with os.fdopen(descriptor, "w", encoding="utf-8") as file:
                    descriptor = None
                    json.dump({"version": 1, "tokens": tokens}, file, ensure_ascii=True, allow_nan=False)
                    file.flush()
                    os.fsync(file.fileno())
                os.replace(temporary, self.index_path)
            finally:
                if descriptor is not None:
                    os.close(descriptor)
                if os.path.exists(temporary):
                    os.unlink(temporary)

    def has_tokens(self, tokens):
        """Check saved card references without extending their original lifetime."""
        with self.index_lock:
            now = time.monotonic()
            for token in tokens:
                item = self.owned.get(token)
                if item is None or item[1] <= now or self._indexed_path(item[0].name) != item[0]:
                    return False
            return True

    def install(self):
        async def handle_file(token):
            with self.index_lock:
                item = self.owned.get(token)
                if item is not None:
                    path, expiry = item
                    if time.monotonic() >= expiry or self._indexed_path(path.name) != path:
                        self.owned.pop(token, None)
                        self._save_index()
                        raise FileNotFoundError("image token expired")
            if item is None:
                return await self.original(token)
            return str(path)
        handle_file._official_cards_original = self.original
        self.wrapper = handle_file
        self.service.handle_file = handle_file

    def close(self):
        if self.service.handle_file is self.wrapper:
            self.service.handle_file = self.original
        # A replacement publisher restores unexpired URLs from the private index.

    def cleanup(self):
        with self.index_lock:
            now = time.monotonic()
            self.owned = {token: item for token, item in self.owned.items() if item[1] > now}
            self._save_index()
            for path in self._cache_files():
                try:
                    if not any(item[0] == path for item in self.owned.values()):
                        path.unlink()
                except OSError:
                    pass

    def _cache_files(self):
        # Only plugin-generated copies with the expected hash filename are eligible.
        for path in self.cache_dir.iterdir():
            if self._indexed_path(path.name) == path:
                yield path

    def _reserve_space(self, required):
        with self.index_lock:
            return self._reserve_space_locked(required)

    def _reserve_space_locked(self, required):
        files = list(self._cache_files())
        total = sum(path.stat().st_size for path in files)
        for path in sorted(files, key=lambda item: item.stat().st_mtime):
            if total + required <= self.max_cache_bytes:
                break
            if path in self.protected_paths:
                continue
            size = path.stat().st_size
            self.owned = {token: item for token, item in self.owned.items() if item[0] != path}
            self._save_index()
            path.unlink()
            total -= size
        if total + required > self.max_cache_bytes:
            raise ValueError("image cache is full")

    async def publish(self, component):
        async with self.publish_lock:
            return await self._publish_locked(component)

    async def publish_batch(self, components):
        if len(components) > self.max_tokens:
            raise ValueError("card image count exceeds token budget")
        async with self.publish_lock:
            paths = []
            for component in components:
                path = Path(await component.convert_to_file_path())
                if path.stat().st_size > self.max_image_bytes:
                    raise ValueError("image exceeds card publishing size limit")
                paths.append(path)
            if sum(path.stat().st_size for path in paths) > self.max_cache_bytes:
                raise ValueError("card images exceed cache budget")
            published = []
            try:
                for component, path in zip(components, paths):
                    result = await self._publish_locked(component, path)
                    token = result[0].rsplit("/", 1)[-1]
                    self.protected_paths.add(self.owned[token][0])
                    published.append(result)
                return published
            finally:
                self.protected_paths.clear()

    async def _publish_locked(self, component, source_path=None):
        source = source_path or Path(await component.convert_to_file_path())
        if source.stat().st_size > self.max_image_bytes:
            raise ValueError("image exceeds card publishing size limit")
        self.cleanup()

        def prepare():
            # Opening the existing image only inspects its dimensions.
            with PILImage.open(source) as img:
                width, height = img.size
                extension = {"PNG": ".png", "JPEG": ".jpg", "GIF": ".gif", "WEBP": ".webp", "BMP": ".bmp"}.get(img.format)
                if width <= 0 or height <= 0:
                    raise ValueError("invalid image size")
                if not extension:
                    raise ValueError("unsupported image format")
            hasher = hashlib.sha256()
            with source.open("rb") as file:
                for chunk in iter(lambda: file.read(1024 * 1024), b""):
                    hasher.update(chunk)
            target = self.cache_dir / f"{hasher.hexdigest()}{extension}"
            if not target.exists():
                self._reserve_space(source.stat().st_size)
                shutil.copyfile(source, target)
            target.touch()
            display_width = min(width, 1024)
            display_height = max(1, round(height * display_width / width))
            return target, display_width, display_height

        path, width, height = await asyncio.to_thread(prepare)
        token = await self.service.register_file(str(path), timeout=self.ttl)
        # Remove the one-shot backing record without changing its shared registry.
        await self.original(token)
        with self.index_lock:
            self.owned[token] = (path, time.monotonic() + self.ttl)
            if len(self.owned) > self.max_tokens:
                self.owned.pop(min(self.owned, key=lambda key: self.owned[key][1]))
                self.cleanup()
            else:
                self._save_index()
        return f"{self.base_url}/api/file/{token}", width, height


class CardTransport:
    def __init__(self, publisher, *, keyboard=True, max_markdown_chars=12000):
        self.publisher = publisher
        self.keyboard = bool(keyboard)
        self.max_markdown_chars = max(1000, min(int(max_markdown_chars), 20000))
        self.event_wrapper = self.session_wrapper = None
        self.original_event = self.original_session = None
        self.disabled_keyboard = set()
        self.disabled_markdown = set()
        self.keyboard_pages = KeyboardPageStore()
        self.menu_receipts = MenuReceiptStore()
        self.button_receipts = ButtonReceiptStore()
        self.button_prompts = ButtonPromptStore()
        self.callback_actions = CallbackActionStore()
        self.callbacks_enabled = False
        # Complete publishing and API submission before another card can evict
        # any URL from this card's temporary image batch.
        self.send_lock = asyncio.Lock()

    def install(self):
        self.publisher.install()
        old = QQOfficialMessageEvent._post_send_one
        self.original_event = getattr(old, "_official_cards_original", old)
        old_session = QQOfficialPlatformAdapter._send_by_session_common
        self.original_session = getattr(old_session, "_official_cards_original", old_session)

        async def event_wrapper(event, chain, stream=None):
            async with self.send_lock:
                return await self.send_event(event, chain, stream)

        async def session_wrapper(adapter, session, chain):
            type_name = getattr(session.message_type, "name", str(session.message_type))
            if type_name not in ("GROUP_MESSAGE", "FRIEND_MESSAGE"):
                return await self.original_session(adapter, session, chain)
            async with self.send_lock:
                return await self.send_session(adapter, session, chain)

        event_wrapper._official_cards_original = self.original_event
        session_wrapper._official_cards_original = self.original_session
        self.event_wrapper, self.session_wrapper = event_wrapper, session_wrapper
        QQOfficialMessageEvent._post_send_one = event_wrapper
        QQOfficialPlatformAdapter._send_by_session_common = session_wrapper

    def close(self):
        if QQOfficialMessageEvent._post_send_one is self.event_wrapper:
            QQOfficialMessageEvent._post_send_one = self.original_event
        if QQOfficialPlatformAdapter._send_by_session_common is self.session_wrapper:
            QQOfficialPlatformAdapter._send_by_session_common = self.original_session
        self.publisher.close()
        self.keyboard_pages.clear()
        self.menu_receipts.clear()
        self.button_receipts.clear()
        self.button_prompts.clear()
        self.callback_actions.clear()

    async def render(self, chain, hint, *, published_tokens=None):
        components = flatten_components(chain.chain)
        if any(not isinstance(c, (Plain, Image, At, AtAll, Reply)) for c in components):
            return None, components
        chunks = []
        images = [component for component in components if isinstance(component, Image)]
        published = iter(await self.publisher.publish_batch(images))
        title = str(hint.get("title") or "").replace("\n", " ").strip()[:100]
        if title:
            chunks.append("## " + title)
        for component in components:
            if isinstance(component, Plain):
                chunks.append(component.text)
            elif isinstance(component, Image):
                url, width, height = next(published)
                if published_tokens is not None:
                    published_tokens.append(urlparse(url).path.rsplit('/', 1)[-1])
                chunks.append(f"![图片 #{width}px #{height}px]({url})")
        content = "\n\n".join(chunk for chunk in chunks if chunk)
        if not content or len(content) > self.max_markdown_chars:
            return None, components
        return content, components

    async def render_help(self, event, chain, hint, buttons):
        """Convert only text menus. Existing artwork and query results survive."""
        components = flatten_components(chain.chain)
        if any(not isinstance(c, (Plain, At, AtAll, Reply)) for c in components):
            return None
        if event.get_extra(PAGE_HINT_KEY, None):
            return None  # Page snapshots already contain the matching image.
        text = '\n'.join(c.text for c in components if isinstance(c, Plain))
        spec = category_image_spec(event)
        title = text_help_title(event, hint, text) if not spec else None
        if not spec and not title:
            return None
        cache = Path(getattr(self.publisher, 'cache_dir', tempfile.gettempdir())) / 'help_menu_images'
        if spec:
            normalized = normalize_buttons(buttons)
            page_size = 8 if len(normalized) > 10 else 10
            count = max(1, math.ceil(len(normalized) / page_size))
            def render_pages():
                return [render_command_menu(*spec, normalized, cache_dir=cache, page=page, page_size=page_size)
                        for page in range(1, count + 1)]
            paths = await asyncio.to_thread(render_pages)
            images = [Image.fromFileSystem(str(path)) for path in paths]
            published = await self.publisher.publish_batch(images)
            cards = tuple((f'![菜单 #{width}px #{height}px]({url})',
                           (urlparse(url).path.rsplit('/', 1)[-1],)) for url, width, height in published)
            return cards[0][0], images, cards[0][1], cards if count > 1 else ()
        paths = await asyncio.to_thread(render_text_menu, title, text, cache_dir=cache)
        rendered = chain.derive([Image.fromFileSystem(str(path)) for path in paths])
        tokens = []
        content, components = await self.render(rendered, {}, published_tokens=tokens)
        return content, components, tuple(tokens), ()

    async def _send_with_capabilities(self, send, payload, key, *, without_keyboard_content=None):
        try:
            return require_receipt(await send(payload))
        except Exception as error:
            reason = explicit_rejection(error)
            if reason == "keyboard" and payload.get("keyboard"):
                self.disabled_keyboard.add(key)
                logger.info("[OfficialCards] QQ rejected keyboard capability; continuing without buttons.")
                payload = {k: value for k, value in payload.items() if k != "keyboard"}
                if without_keyboard_content:
                    payload['markdown'] = {'content': without_keyboard_content}
                try:
                    return require_receipt(await send(payload))
                except Exception as next_error:
                    if explicit_rejection(next_error) == "markdown":
                        self.disabled_markdown.add(key)
                        return _FALLBACK
                    raise
            if reason == "markdown":
                self.disabled_markdown.add(key)
                logger.info("[OfficialCards] QQ rejected Markdown capability; using original message components.")
                return _FALLBACK
            # Never retry a timeout, connection error, frequency limit or unknown API error.
            raise

    def _payload(self, content, buttons, key, *, msg_id=None, guild=False, event=None, callback_scope=None, image_tokens=(), page_cards=()):
        page = None
        setter = getattr(event, 'set_extra', None)
        if setter:
            setter(MENU_RECEIPT_HINT_KEY, None)
            setter(OUTGOING_BUTTONS_KEY, None)
        navigation_commands = frozenset()
        internal_enter_commands = set()
        buttons = normalize_buttons(buttons)
        if self.keyboard and key not in self.disabled_keyboard:
            getter = getattr(event, "get_extra", None)
            request = getter(PAGE_HINT_KEY, None) if getter else None
            if buttons and isinstance(request, tuple) and len(request) == 2:
                page = self.keyboard_pages.get_page(request[0], request[1], event)
                if page is None or (page.image_tokens and not self.publisher.has_tokens(page.image_tokens)):
                    page = None
                    buttons = [dict(HOME_BUTTON)]
                    content = '这个菜单已过期或不属于当前会话，请重新发送帮助命令。'
                else:
                    buttons, navigation_commands = page.buttons, page.navigation_commands
                    content = page.text
            elif len(buttons) > 10:
                page = self.keyboard_pages.create(buttons, event, card_content=content, image_tokens=image_tokens, page_cards=page_cards)
                if page is not None:
                    buttons, navigation_commands = page.buttons, page.navigation_commands
                    content = page.text
            buttons, overflow = unbound_keyboard(buttons)
            if overflow:
                content += "\n\n" + overflow
            # Incomplete input helpers now reply with usage immediately. Never
            # auto-submit a bare delete/switch command merely to produce a reply.
            ready = []
            for item in buttons:
                item = dict(item)
                if self.callbacks_enabled and not item['enter'] and item['command'] not in navigation_commands:
                    command = self.button_prompts.create(item['label'], item['command'], event)
                    if command is not None:
                        internal_enter_commands.add(command)
                        item.update(command=command, enter=True)
                    else:
                        # Proactive messages have no requesting user to bind a
                        # prompt to. Keep the command visible and open the menu.
                        content += f"\n\n{item['label']}：{item['command']}"
                        item.update(command=HOME_BUTTON['command'], enter=True)
                ready.append(item)
            buttons = ready
        payload = {"markdown": {"content": content}}
        if not guild:
            payload.update(msg_type=2, msg_seq=random.randint(1, 10000))
        if msg_id:
            payload["msg_id"] = msg_id
        interaction_id = event.get_extra('qqofficial_interaction_event_id', None) if event and hasattr(event, 'get_extra') else None
        if interaction_id:
            payload.pop('msg_id', None)
            payload['event_id'] = interaction_id
        if self.keyboard and key not in self.disabled_keyboard:
            actions = None
            if self.callbacks_enabled and not guild:
                actions = {}
                for item in buttons:
                    action = self.callback_actions.create(item['command'], event, scope=callback_scope)
                    if action is None:
                        logger.warning('[OfficialCards] Callback has no verified destination; keyboard omitted.')
                        return payload
                    actions[item['command']] = action
            keyboard = build_keyboard(buttons, navigation_commands=navigation_commands,
                                      internal_enter_commands=frozenset(internal_enter_commands), callback_actions=actions)
            if keyboard:
                payload["keyboard"] = keyboard
                if actions and setter and not guild:
                    setter(OUTGOING_BUTTONS_KEY, tuple(action['data'] for action in actions.values()))
                if page is not None and setter and not guild:
                    setter(MENU_RECEIPT_HINT_KEY, (page.token, page.number))
        return payload

    async def _original_event(self, event, chain, components=None, force_plain=False):
        fallback = chain.derive(components if components is not None else chain.chain)
        source = event.message_obj.raw_message
        if isinstance(source, botpy.message.GroupMessage):
            target, scene = source.group_openid, "group"
        elif isinstance(source, botpy.message.C2CMessage):
            target, scene = source.author.user_openid, "friend"
        elif isinstance(source, botpy.message.DirectMessage):
            target, scene = source.guild_id, "guild_dm"
        elif isinstance(source, botpy.message.Message):
            target, scene = source.channel_id, "channel"
        else:
            return await self.original_event(event, chain, None)
        # Core's ordinary send wrapper retries unrelated errors as proactive
        # messages. Reuse its conversion/upload helpers without that retry.
        interaction_id = event.get_extra('qqofficial_interaction_event_id', None) if hasattr(event, 'get_extra') else None
        sent = await self._send_plain_session(SimpleNamespace(client=event.bot), target, scene,
                                               fallback, event.message_obj.message_id, event_id=interaction_id)
        if sent is True:
            if not is_pending_delivery(event, chain, fallback.chain):
                await self.button_receipts.after_reply(event, None, confirmed_plain=True)
            await AstrMessageEvent.send(event, chain)
            return {'_qqofficial_send_confirmed': True}
        return None

    async def send_event(self, event, chain, stream=None):
        interaction_id = event.get_extra('qqofficial_interaction_event_id', None) if hasattr(event, 'get_extra') else None
        if stream and not interaction_id:
            return await self.original_event(event, chain, stream)
        source = event.message_obj.raw_message
        key = (event.get_platform_id(), type(source).__name__, "passive")
        hint = get_card_hint(event)
        original_chain = event.send_buffer or chain
        dynamic = getattr(chain, "qqofficial_buttons", None) or getattr(original_chain, "qqofficial_buttons", None)
        buttons = dynamic or buttons_for_event(event, hint)
        if original_chain.chain and chain.chain and chain.chain[-1] is not original_chain.chain[-1]:
            buttons = []
        if chain.use_markdown_ is False or key in self.disabled_markdown:
            components = flatten_components(chain.chain)
            try:
                prepared = await self.render_help(event, chain, hint, buttons)
                if prepared is not None:
                    components = prepared[1]
            except (ValueError, OSError, RuntimeError):
                logger.info('[OfficialCards] Plain help image preparation unavailable.')
            return await self._original_event(event, chain, components, True)
        image_tokens = []
        page_cards = ()
        try:
            help_image = await self.render_help(event, chain, hint, buttons)
            if help_image is not None:
                content, components, image_tokens, page_cards = help_image
            else:
                content, components = await self.render(chain, hint, published_tokens=image_tokens)
        except (ValueError, OSError, RuntimeError):
            if category_image_spec(event):
                logger.info('[OfficialCards] Category menu image unavailable.')
                content = '菜单图片暂时生成失败，请稍后重新打开功能菜单。'
                components, buttons = [Plain(content)], [dict(HOME_BUTTON)]
                image_tokens, page_cards = (), ()
            else:
                logger.info("[OfficialCards] Image card preparation unavailable; using original components.")
                return await self._original_event(event, chain, flatten_components(chain.chain))
        if content is None:
            return await self._original_event(event, chain, components)
        api = event.bot.api
        if isinstance(source, botpy.message.GroupMessage):
            send = lambda payload: api.post_group_message(group_openid=source.group_openid, **payload)
        elif isinstance(source, botpy.message.C2CMessage):
            send = lambda payload: api.post_c2c_message(openid=source.author.user_openid, **payload)
        elif isinstance(source, botpy.message.DirectMessage):
            send = lambda payload: api.post_dms(guild_id=source.guild_id, **payload)
        elif isinstance(source, botpy.message.Message):
            send = lambda payload: api.post_message(channel_id=source.channel_id, **payload)
        else:
            return await self._original_event(event, chain, components)
        guild = isinstance(source, (botpy.message.Message, botpy.message.DirectMessage))
        payload = self._payload(content, buttons, key, msg_id=event.message_obj.message_id, guild=guild,
                                event=event, image_tokens=tuple(image_tokens), page_cards=page_cards)
        full_image_content = '\n\n'.join(card[0] for card in page_cards) if page_cards else None
        if full_image_content and not payload.get('keyboard'):
            payload['markdown'] = {'content': full_image_content}
        receipt_hint = event.get_extra(MENU_RECEIPT_HINT_KEY, None) if hasattr(event, 'get_extra') else None
        outgoing_buttons = event.get_extra(OUTGOING_BUTTONS_KEY, None) if hasattr(event, 'get_extra') else None
        if hasattr(event, 'set_extra'):
            event.set_extra(MENU_RECEIPT_HINT_KEY, None)
            event.set_extra(OUTGOING_BUTTONS_KEY, None)
        submitted_at = self.menu_receipts.clock()
        result = await self._send_with_capabilities(send, payload, key, without_keyboard_content=full_image_content)
        if result is _FALLBACK:
            return await self._original_event(event, chain, components, True)
        clicked_card = event.get_extra(CLICKED_CARD_KEY, None) if hasattr(event, 'get_extra') else None
        if (not guild and payload.get('keyboard') and key not in self.disabled_keyboard
                and key not in self.disabled_markdown and isinstance(outgoing_buttons, tuple)):
            self.button_receipts.bind(event, outgoing_buttons, result, submitted_at)
        if not is_pending_delivery(event, chain, components):
            await self.button_receipts.after_reply(event, result)
        if (not guild and payload.get('keyboard') and key not in self.disabled_keyboard
                and key not in self.disabled_markdown and isinstance(receipt_hint, tuple)
                and len(receipt_hint) == 2
                and self.keyboard_pages.get_page(receipt_hint[0], receipt_hint[1], event) is not None):
            # A callback may only withdraw its own confirmed source card.
            # Missing/evicted provenance must not fall back to a latest page.
            await self.menu_receipts.complete(event, *receipt_hint, result, submitted_at, recall=not clicked_card)
        await AstrMessageEvent.send(event, chain)
        return result

    async def send_session(self, adapter, session, chain):
        scene = adapter._session_scene.get(session.session_id)
        type_name = getattr(session.message_type, "name", str(session.message_type))
        target = session.session_id
        if scene is None and type_name == "GROUP_MESSAGE" and target.startswith("0_"):
            legacy_target = target[2:]
            if adapter._session_scene.get(legacy_target) in ("group", "channel"):
                target, scene = legacy_target, adapter._session_scene[legacy_target]
        if type_name == "GROUP_MESSAGE" and scene not in ("group", "channel"):
            logger.info("[OfficialCards] Unknown QQ group session scene; delivery skipped.")
            return None
        if type_name not in ("GROUP_MESSAGE", "FRIEND_MESSAGE"):
            return await self.original_session(adapter, session, chain)
        if type_name == "FRIEND_MESSAGE" and scene not in (None, "friend"):
            logger.info("[OfficialCards] QQ private session scene mismatch; delivery skipped.")
            return None
        proactive = type_name == "FRIEND_MESSAGE" or (
            type_name == "GROUP_MESSAGE" and scene == "group" and adapter._allow_group_proactive_send
        )
        msg_id = None if proactive else adapter._session_last_message_id.get(target)
        if not msg_id and not proactive:
            logger.info("[OfficialCards] No inbound message ID for this QQ session; delivery skipped.")
            return None
        source_name = {"group": "GroupMessage", "channel": "Message"}.get(scene, "C2CMessage")
        key = (adapter.meta().id, source_name, "proactive" if proactive else "passive")
        components = flatten_components(chain.chain)
        fallback = chain.derive(components)
        if key in self.disabled_markdown or chain.use_markdown_ is False or (
            chain.use_markdown_ is None and not adapter.use_markdown_default
        ):
            return await self._send_plain_session(adapter, target, scene, fallback, msg_id)
        try:
            content, components = await self.render(chain, {})
        except (ValueError, OSError):
            content = None
        if content is None:
            return await self._send_plain_session(adapter, target, scene, fallback, msg_id)
        buttons = getattr(chain, "qqofficial_buttons", [])
        payload = self._payload(content, buttons, key, msg_id=None if proactive else msg_id, guild=scene == "channel",
                                callback_scope=(adapter.meta().id, 'group' if scene == 'group' else 'c2c', target))
        api = adapter.client.api
        if type_name == "FRIEND_MESSAGE":
            send = lambda data: api.post_c2c_message(openid=target, **data)
        elif scene == "channel":
            send = lambda data: api.post_message(channel_id=target, **data)
        else:
            send = lambda data: api.post_group_message(group_openid=target, **data)
        result = await self._send_with_capabilities(send, payload, key)
        if result is _FALLBACK:
            return await self._send_plain_session(adapter, target, scene, fallback, msg_id)
        # A bot's outbound receipt is not a user message that grants passive replies.
        # Keep the most recent inbound message ID recorded by the receive path.
        return None

    async def _send_plain_session(self, adapter, target, scene, chain, msg_id, *, event_id=None):
        """Reuse core media conversion/upload, preserving the exact verified target.

        Core's session fallback rsplit('_') would truncate opaque IDs. Sending
        the parsed payload here also avoids its retry as an unrelated proactive
        message after permission denial.
        """
        api = adapter.client.api
        helper = SimpleNamespace(bot=adapter.client)
        sent = False
        for part in QQOfficialMessageEvent._split_message_chain_by_media(chain):
            text, image, image_path, record, video, file, filename = await QQOfficialMessageEvent._parse_to_qqofficial(part)
            if not any((text, image, image_path, record, video, file)):
                continue
            payload = {"content": text}
            if event_id:
                payload['event_id'] = event_id
            elif msg_id:
                payload["msg_id"] = msg_id
            if scene in ("channel", "guild_dm"):
                if image_path:
                    payload["file_image"] = image_path
                if scene == "channel":
                    require_receipt(await api.post_message(channel_id=target, **payload))
                else:
                    require_receipt(await api.post_dms(guild_id=target, **payload))
                sent = True
                continue
            destination = {"group_openid": target} if scene == "group" else {"openid": target}
            payload.update(msg_type=0, msg_seq=random.randint(1, 10000))
            media = None
            if image:
                media = await QQOfficialMessageEvent.upload_group_and_c2c_image(helper, image, 1, **destination)
            elif record or video or file:
                file_type = 3 if record else (2 if video else 4)
                media = await QQOfficialMessageEvent.upload_group_and_c2c_media(
                    helper, record or video or file, file_type, file_name=filename, **destination)
            if media:
                payload.update(msg_type=7, media=media, content=text or " ")
            send = api.post_group_message if scene == "group" else api.post_c2c_message
            require_receipt(await send(**destination, **payload))
            sent = True
        return sent


_FALLBACK = object()
