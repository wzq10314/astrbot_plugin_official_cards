"""Optional hints for plugins; plain event.send also works without hints."""
from __future__ import annotations

CARD_HINT_KEY = "qq_official_card"


def is_qq_official(event) -> bool:
    # Hints are safe metadata on both adapters. Transport installation remains
    # restricted to the verified WebSocket adapter classes.
    return event.get_platform_name() in ("qq_official", "qq_official_webhook")


def set_card_hint(event, *, title=None, family=None, buttons=None) -> None:
    hint = get_card_hint(event)
    for key, value in (("title", title), ("family", family), ("buttons", buttons)):
        if value is not None:
            hint[key] = value
    event.set_extra(CARD_HINT_KEY, hint)


def get_card_hint(event) -> dict:
    getter = getattr(event, "get_extra", None)
    value = getter(CARD_HINT_KEY, {}) if getter else {}
    return dict(value) if isinstance(value, dict) else {}


def qq_user_label(event) -> str:
    """OpenIDs are identifiers, never QQ numbers or an avatar-service input."""
    name = str(event.get_sender_name() or "").strip()
    return name or "QQ用户"


def button(label: str, command: str, *, enter: bool = False) -> dict:
    """Only trusted, static menu commands should request immediate submission."""
    return {"label": label, "command": command, "enter": bool(enter)}
