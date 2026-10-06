"""Send existing help routes through the normal command pipeline, once."""
from __future__ import annotations

import copy
import re

from astrbot.api.message_components import At, Plain
from .button_receipts import CLICKED_CARD_KEY


HELP_ROUTES = {
    "光遇": "/光遇帮助",
    "签到": "/签到帮助",
    "王者": "#王者帮助",
    "音乐": "#R帮助",
    "Pixiv": "/pixiv帮助",
    "Pica": "/pica帮助",
    "JM": "/jm帮助",
}
_ALIASES = {
    "sky": "光遇", "get_px": "签到", "gloryofkings": "王者", "rconsole": "音乐",
    "pixiv": "Pixiv", "pica": "Pica", "jm": "JM",
}
_ALIASES.update({name.casefold(): name for name in HELP_ROUTES})
_ROUTED_KEY = "qq_official_original_help_queued"
_INTERACTION_KEY = "qqofficial_interaction_event_id"


def original_help_command(category: str) -> str | None:
    """Only exact known category names/aliases select an existing help handler."""
    if not isinstance(category, str) or any(char in category for char in "\r\n"):
        return None
    return HELP_ROUTES.get(_ALIASES.get(category.strip().casefold(), ""))


def route_menu_command(command: str) -> str:
    """Resolve old menu callbacks without accepting parameters or other commands."""
    if not isinstance(command, str) or any(char in command for char in "\r\n"):
        return command
    match = re.fullmatch(r"[/#]?(?:功能菜单|官方菜单)[ \t]+([^ \t]+)", command.strip())
    return (original_help_command(match[1]) or command) if match else command


def _matching_adapter(context, event):
    platform_id = event.get_platform_id()
    platform_name = event.get_platform_name()
    if platform_name != "qq_official" or not isinstance(platform_id, str) or not platform_id:
        return None
    manager = getattr(context, "platform_manager", None)
    getter = getattr(manager, "get_insts", None)
    candidates = list(getter() or ()) if callable(getter) else list(getattr(manager, "platform_insts", ()) or ())
    attached = getattr(getattr(event, "bot", None), "platform", None)
    if attached is not None and not candidates:
        candidates = [attached]
    for adapter in candidates:
        if not callable(getattr(adapter, "create_event", None)) or not callable(getattr(adapter, "commit_event", None)):
            continue
        metadata = adapter.meta()
        if metadata.id == platform_id and metadata.name == platform_name:
            return adapter
    return None


def queue_original_help(context, event, category: str) -> bool:
    """Queue a fresh event, retaining actor/destination and normal permission checks.

    The caller stops its current handler only after True. No plugin method is
    invoked here, and no SDK message, send buffer, role or parsed handler state
    is modified/copied into the newly constructed event.
    """
    command = original_help_command(category)
    if command is None:
        return False
    try:
        prior = event.get_extra(_ROUTED_KEY, None)
        if prior is not None:
            return prior == command
        adapter = _matching_adapter(context, event)
        if adapter is None:
            return False
        original = event.message_obj
        message = copy.copy(original)
        mentions = [copy.copy(item) for item in getattr(original, "message", ()) if isinstance(item, At)]
        message_type = getattr(getattr(original, "type", None), "name", "")
        if message_type == "GROUP_MESSAGE":
            self_id = str(getattr(original, "self_id", "") or "")
            if not self_id:
                return False
            if not any(str(getattr(item, "qq", "")) == self_id for item in mentions):
                # WakingCheckStage recomputes wake from the message components;
                # its local flag does not use a pre-set event.is_wake value.
                mentions.insert(0, At(qq=self_id))
        elif message_type != "FRIEND_MESSAGE":
            return False
        message.message = [*mentions, Plain(command)]
        message.message_str = command
        routed = adapter.create_event(message)
        routed.is_wake = True
        routed.is_at_or_wake_command = True
        routed.should_call_llm(True)
        plugins = getattr(event, "plugins_name", None)
        routed.plugins_name = list(plugins) if isinstance(plugins, list) else plugins
        interaction_id = event.get_extra(_INTERACTION_KEY, None)
        if interaction_id:
            routed.set_extra(_INTERACTION_KEY, interaction_id)
        clicked_card = event.get_extra(CLICKED_CARD_KEY, None)
        if clicked_card:
            routed.set_extra(CLICKED_CARD_KEY, clicked_card)
        if event.get_extra("_api_key_allow_admin_role", None) is False:
            routed.set_extra("_api_key_allow_admin_role", False)
        routed.set_extra(_ROUTED_KEY, command)
    except (AttributeError, TypeError, ValueError):
        return False
    # Platform.commit_event only does put_nowait. Mark the source first so even
    # a later call in this handler cannot enqueue a second copy.
    event.set_extra(_ROUTED_KEY, command)
    try:
        adapter.commit_event(routed)
    except Exception:
        event.set_extra(_ROUTED_KEY, None)
        return False
    return True
