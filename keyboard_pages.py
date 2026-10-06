"""Short-lived, owner-bound snapshots for QQ's two-column keyboards."""
from __future__ import annotations

import secrets
import time
from collections import OrderedDict
from dataclasses import dataclass


PAGE_HINT_KEY = "qq_official_keyboard_page"
PAGE_SIZE = 8
MAX_BUTTONS = 256
MAX_CARD_CONTENT_CHARS = 20000
MAX_IMAGE_TOKENS = 256
HOME_BUTTON = {"label": "功能菜单", "command": "/功能菜单", "enter": True}


def event_owner(event):
    """Never create a replayable menu when the sender or scene is unknown."""
    if event is None:
        return None
    try:
        platform = event.get_platform_id()
        session = event.get_session_id()
        sender = event.get_sender_id()
        scene = type(event.message_obj.raw_message).__name__
        admin = bool(event.is_admin())
    except (AttributeError, TypeError):
        return None
    if not all(isinstance(value, str) and value for value in (platform, session, sender)):
        return None
    return platform, scene, session, sender, admin


@dataclass(frozen=True)
class KeyboardPage:
    token: str
    number: int
    total: int
    buttons: list[dict]
    navigation_commands: frozenset[str]
    card_content: str = ""
    image_tokens: tuple[str, ...] = ()

    @property
    def text(self):
        if self.card_content:
            return f"{self.card_content}\n\n按钮第 {self.number}/{self.total} 页"
        lines = [f"操作菜单 · 第 {self.number}/{self.total} 页"]
        for item in self.buttons:
            if item["command"] not in self.navigation_commands:
                lines.append(f'{item["label"]}：{item["command"]}')
        lines.append("点击按钮选择操作；翻页不会执行操作。")
        return "\n\n".join(lines)


class KeyboardPageStore:
    def __init__(self, *, ttl=3600, max_entries=256, clock=time.monotonic):
        self.ttl = max(1, min(float(ttl), 3600))
        self.max_entries = max(1, min(int(max_entries), 256))
        self.clock = clock
        self.entries = OrderedDict()

    def clear(self):
        self.entries.clear()

    def _cleanup(self):
        now = self.clock()
        for token, entry in list(self.entries.items()):
            if entry[0] <= now:
                del self.entries[token]

    def create(self, buttons, event, *, card_content="", image_tokens=(), page_cards=()):
        owner = event_owner(event)
        if owner is None or not 10 < len(buttons) <= MAX_BUTTONS:
            return None
        if not isinstance(card_content, str) or len(card_content) > MAX_CARD_CONTENT_CHARS:
            return None
        if not isinstance(image_tokens, (tuple, list)) or len(image_tokens) > MAX_IMAGE_TOKENS:
            return None
        if any(not isinstance(token, str) or not 0 < len(token) <= 512
               or any(ord(char) < 32 for char in token) for token in image_tokens):
            return None
        total = (len(buttons) + PAGE_SIZE - 1) // PAGE_SIZE
        if not isinstance(page_cards, (tuple, list)) or (page_cards and len(page_cards) != total):
            return None
        frozen_cards = []
        for card in page_cards:
            if not isinstance(card, (tuple, list)) or len(card) != 2:
                return None
            content, tokens = card
            if not isinstance(content, str) or not content or len(content) > MAX_CARD_CONTENT_CHARS:
                return None
            if not isinstance(tokens, (tuple, list)) or len(tokens) > MAX_IMAGE_TOKENS:
                return None
            if any(not isinstance(token, str) or not 0 < len(token) <= 512
                   or any(ord(char) < 32 for char in token) for token in tokens):
                return None
            frozen_cards.append((content, tuple(tokens)))
        if sum(len(tokens) for _, tokens in frozen_cards) > MAX_IMAGE_TOKENS:
            return None
        self._cleanup()
        token = secrets.token_urlsafe(18)
        # Store values, not the caller's mutable dictionaries. Never persist
        # account/action menus to disk, and do not extend expiry while paging.
        snapshot = tuple((b["label"], b["command"], bool(b["enter"])) for b in buttons)
        # Retain only rendered text and publisher-owned token names. No event,
        # client, mutable message chain, or source image path belongs here.
        self.entries[token] = (self.clock() + self.ttl, owner, snapshot,
                               card_content, tuple(image_tokens), tuple(frozen_cards))
        while len(self.entries) > self.max_entries:
            self.entries.popitem(last=False)
        return self.get_page(token, 1, event)

    def get_page(self, token, number, event):
        if not isinstance(token, str) or not isinstance(number, int) or isinstance(number, bool):
            return None
        self._cleanup()
        entry = self.entries.get(token)
        if entry is None or event_owner(event) != entry[1]:
            return None
        snapshot = entry[2]
        total = (len(snapshot) + PAGE_SIZE - 1) // PAGE_SIZE
        if not 1 <= number <= total:
            return None
        start = (number - 1) * PAGE_SIZE
        buttons = [{"label": label, "command": command, "enter": enter}
                   for label, command, enter in snapshot[start:start + PAGE_SIZE]]
        navigation = set()
        for target, label in ((number - 1, "上一页"), (number + 1, "下一页")):
            if 1 <= target <= total:
                command = f"/菜单翻页 {token} {target}"
                navigation.add(command)
                buttons.append({"label": f"{label} {target}/{total}", "command": command, "enter": True})
        content, tokens = entry[5][number - 1] if entry[5] else (entry[3], entry[4])
        return KeyboardPage(token, number, total, buttons, frozenset(navigation), content, tokens)


def unbound_keyboard(buttons):
    """A proactive message has no requesting user; expose overflow as text."""
    if len(buttons) <= 10:
        return buttons, ""
    visible = [dict(item) for item in buttons[:9]]
    if any(item["command"] == HOME_BUTTON["command"] for item in visible):
        visible.append(dict(buttons[9]))
        remaining = buttons[10:]
    else:
        visible.append(dict(HOME_BUTTON))
        remaining = [item for item in buttons[9:] if item["command"] != HOME_BUTTON["command"]]
    lines = ["更多操作（手动输入命令）："]
    lines.extend(f'{item["label"]}：{item["command"]}' for item in remaining)
    return visible, "\n\n".join(lines)
