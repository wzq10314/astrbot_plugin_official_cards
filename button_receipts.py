"""Withdraw a confirmed button card only after its creator receives a reply.

Callback message IDs are deliberately never consulted. Opaque tokens belong to
receipts returned by our own API calls, with the original destination and user.
"""
from __future__ import annotations

import asyncio
import math
import re
import time
from collections import OrderedDict
from dataclasses import dataclass

from astrbot.api import logger

from .keyboard_pages import event_owner
from .menu_receipts import MenuReceiptStore, SCENES


CLICKED_CARD_KEY = "qq_official_clicked_card"
OUTGOING_BUTTONS_KEY = "qq_official_outgoing_buttons"
_TOKEN_PATTERN = re.compile(r"oc:[A-Za-z0-9_-]{24}\Z")


@dataclass(frozen=True)
class ButtonReceipt:
    platform: str
    scene: str
    destination: str
    sender: str
    message_id: str
    submitted_at: float


def _event_context(event):
    owner = event_owner(event)
    if owner is None:
        return None
    platform, raw_scene, destination, sender, _ = owner
    scene = SCENES.get(raw_scene)
    try:
        source = event.message_obj.raw_message
        if scene == "group":
            target = getattr(source, "group_openid", None)
        elif scene == "c2c":
            target = getattr(getattr(source, "author", None), "user_openid", None)
        else:
            return None
    except (AttributeError, TypeError):
        return None
    if not isinstance(target, str) or not target or target != destination:
        return None
    return platform, scene, destination, sender


def _failed_response(response):
    return isinstance(response, dict) and (
        response.get("status") == "failed"
        or any(response.get(key) not in (None, 0, "0") for key in ("code", "retcode", "errcode"))
    )


def _response_id(response):
    if _failed_response(response):
        return None
    if isinstance(response, dict):
        value = response.get("id") or response.get("message_id")
    else:
        value = getattr(response, "id", None) or getattr(response, "message_id", None)
    if not isinstance(value, str) or not value.strip() or len(value) > 2048:
        return None
    return value


class ButtonReceiptStore:
    def __init__(self, *, clock=time.monotonic, max_entries=256, max_age=115):
        self.clock = clock
        self.max_entries = max(1, min(int(max_entries), 256))
        # A five-second deletion deadline fits before QQ's two-minute limit.
        self.max_age = max(1, min(float(max_age), 115))
        self.entries = OrderedDict()
        self.tokens = {}
        self.receipt_tokens = {}
        self.attempted = set()

    def clear(self):
        self.entries.clear()
        self.tokens.clear()
        self.receipt_tokens.clear()
        self.attempted.clear()

    def _forget(self, key):
        self.entries.pop(key, None)
        for token in self.receipt_tokens.pop(key, ()):
            if self.tokens.get(token) == key:
                del self.tokens[token]
        self.attempted.discard(key)

    def bind(self, event, tokens, response, submitted_at):
        """Bind locally minted callback tokens after confirmed card delivery."""
        context = _event_context(event)
        message_id = _response_id(response)
        if context is None or message_id is None or not isinstance(tokens, tuple):
            return
        now = self.clock()
        if (
            not isinstance(submitted_at, (int, float))
            or isinstance(submitted_at, bool)
            or not math.isfinite(submitted_at)
            or not 0 <= now - submitted_at
        ):
            return
        platform, scene, destination, sender = context
        key = (platform, scene, destination, message_id)
        previous = self.entries.get(key)
        # The same API ID must never acquire a different creator or timestamp.
        if previous is not None and previous.sender != sender:
            return
        valid_tokens = tuple(dict.fromkeys(
            token for token in tokens
            if isinstance(token, str) and _TOKEN_PATTERN.fullmatch(token)
            and self.tokens.get(token, key) == key
        ))
        if not valid_tokens:
            return
        if previous is None:
            self.entries[key] = ButtonReceipt(
                platform, scene, destination, sender, message_id, submitted_at
            )
            self.receipt_tokens[key] = set()
        for token in valid_tokens:
            self.tokens[token] = key
            self.receipt_tokens[key].add(token)
        # Eviction removes both lookup directions and the attempt marker.
        while len(self.entries) > self.max_entries or len(self.tokens) > 4096:
            self._forget(next(iter(self.entries)))

    def _clicked_receipt(self, event):
        try:
            token = event.get_extra(CLICKED_CARD_KEY)
        except (AttributeError, TypeError):
            return None
        if not isinstance(token, str) or not _TOKEN_PATTERN.fullmatch(token):
            return None
        key = self.tokens.get(token)
        receipt = self.entries.get(key)
        return (key, receipt) if receipt is not None else None

    def has_clicked_source(self, event):
        """Report only whether the token has a confirmed local source receipt."""
        return self._clicked_receipt(event) is not None

    async def after_reply(self, event, response, *, confirmed_plain=False):
        """Attempt source withdrawal once, after a successful substantive reply.

        The caller excludes progress notices. It may set confirmed_plain only
        after a non-card send has completed successfully without a receipt ID.
        """
        clicked = self._clicked_receipt(event)
        if clicked is None or _failed_response(response):
            return False
        key, source = clicked
        context = _event_context(event)
        if context != (source.platform, source.scene, source.destination, source.sender):
            return False
        message_id = _response_id(response)
        if message_id is None and confirmed_plain is not True:
            return False
        if message_id == source.message_id or key in self.attempted:
            return False
        if not 0 <= self.clock() - source.submitted_at < self.max_age:
            return False
        # Claim before awaiting: simultaneous callbacks must not delete twice.
        self.attempted.add(key)
        try:
            ok = await asyncio.wait_for(
                self._delete(event.bot.api, source.scene, source.destination, source.message_id),
                timeout=5.0,
            )
            if ok:
                logger.info("[OfficialCards] Button source withdrawn after creator received a reply.")
        except Exception as exc:
            # Never log callback payloads, response bodies or account IDs.
            logger.warning(
                f"[OfficialCards] Button source withdrawal skipped ({type(exc).__name__}); reply kept."
            )
        return True

    async def _delete(self, api, scene, target, message_id):
        # Reuse the bounded direct DELETE path; SDK retry helpers can swallow
        # timeouts and must not resend or retry a destructive cleanup action.
        return await MenuReceiptStore._delete(self, api, scene, target, message_id)

