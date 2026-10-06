"""Replace only confirmed, owner-bound pagination menus, never user messages."""
from __future__ import annotations

import asyncio
import json
import time
from collections import OrderedDict
from dataclasses import dataclass
from urllib.parse import quote

import aiohttp

from astrbot.api import logger
from .keyboard_pages import event_owner


MENU_RECEIPT_HINT_KEY = "qq_official_menu_receipt"
SCENES = {"GroupMessage": "group", "PatchedGroupMessage": "group",
          "C2CMessage": "c2c", "PatchedC2CMessage": "c2c"}


@dataclass(frozen=True)
class MenuReceipt:
    message_id: str
    submitted_at: float
    page: int


class MenuReceiptStore:
    def __init__(self, *, clock=time.monotonic, max_entries=256, max_age=115):
        self.clock = clock
        self.max_entries = max(1, min(int(max_entries), 256))
        # Leave a small margin before QQ's two-minute withdrawal deadline.
        self.max_age = max(1, min(float(max_age), 115))
        self.entries = OrderedDict()

    def clear(self):
        self.entries.clear()

    async def complete(self, event, menu_token, page, response, submitted_at, *, recall=True):
        """Called only after a valid paginated keyboard has been delivered.

        The normal transport lock serializes send-and-replace. Receipts come
        only from our sends; inbound callback message IDs are never consulted.
        """
        owner = event_owner(event)
        if owner is None or not isinstance(menu_token, str) or not menu_token:
            return
        scene = SCENES.get(owner[1])
        source = event.message_obj.raw_message
        if scene == "group":
            target = getattr(source, "group_openid", None)
        elif scene == "c2c":
            target = getattr(getattr(source, "author", None), "user_openid", None)
        else:
            return
        if target != owner[2] or not isinstance(target, str) or not target:
            return
        if isinstance(response, dict):
            if response.get("status") == "failed" or any(
                response.get(key) not in (None, 0, "0") for key in ("code", "retcode", "errcode")
            ):
                return
            message_id = response.get("id") or response.get("message_id")
        else:
            message_id = getattr(response, "id", None)
        if not isinstance(message_id, str) or not message_id.strip() or len(message_id) > 2048:
            return
        now = self.clock()
        if not isinstance(submitted_at, (int, float)) or not 0 <= now - submitted_at:
            return
        key = (owner, menu_token)
        previous = self.entries.pop(key, None)
        self.entries[key] = MenuReceipt(message_id, submitted_at, page)
        while len(self.entries) > self.max_entries:
            self.entries.popitem(last=False)
        if not recall or previous is None or previous.message_id == message_id:
            return
        if not 0 <= now - previous.submitted_at < self.max_age:
            logger.info("[OfficialCards] Previous menu exceeds withdrawal window; new page kept.")
            return
        try:
            ok = await asyncio.wait_for(
                self._delete(event.bot.api, scene, target, previous.message_id), timeout=5.0
            )
            if ok:
                logger.info("[OfficialCards] Previous pagination menu withdrawn after new page delivery.")
        except Exception as exc:
            # The new page is already delivered. Cleanup must never cause a
            # second send, remove the new page or mask its successful receipt.
            logger.warning(f"[OfficialCards] Previous menu withdrawal skipped ({type(exc).__name__}); new page kept.")

    async def _delete(self, api, scene, target, message_id):
        if scene not in {"group", "c2c"}:
            return False
        http = getattr(api, "_http", None)
        if http is None:
            return False
        await http.check_session()
        host = "sandbox.api.sgroup.qq.com" if http.is_sandbox else "api.bot.qq.com"
        collection = "groups" if scene == "group" else "users"
        url = f"https://{host}/v2/{collection}/{quote(target, safe='')}/messages/{quote(message_id, safe='')}"
        async with http._session.request(
            "DELETE", url, headers=http._headers,
            timeout=aiohttp.ClientTimeout(total=5), allow_redirects=False,
        ) as response:
            status = response.status
            raw = await response.content.read(4097)
            code = None
            body_ok = not raw
            if raw and len(raw) <= 4096:
                try:
                    data = json.loads(raw)
                    if isinstance(data, dict):
                        body_ok = True
                        code = data.get("code", data.get("retcode", data.get("errcode")))
                except (ValueError, UnicodeError):
                    pass
            if status in (200, 204) and body_ok and code in (None, 0, "0"):
                return True
            # Do not include response bodies, identifiers or credentials.
            safe_code = str(code) if isinstance(code, int) or (isinstance(code, str) and code.isdigit()) else "unknown"
            logger.warning(f"[OfficialCards] Previous menu withdrawal rejected (HTTP {status}, code {safe_code}); new page kept.")
            return False
