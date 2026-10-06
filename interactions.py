"""Reversible QQ callback listener; dispatch clicks through normal permissions."""
from __future__ import annotations

import asyncio
import importlib
import logging
import time
from collections import OrderedDict
from .menu_routes import route_menu_command
from .button_receipts import CLICKED_CARD_KEY


INTERACTION_INTENT = 1 << 26
INTERACTION_EVENT_KEY = "qqofficial_interaction_event_id"
_MISSING = object()
try:
    from astrbot.api import logger
except ImportError:
    logger = logging.getLogger(__name__)


def _field(value, name, default=None):
    return value.get(name, default) if isinstance(value, dict) else getattr(value, name, default)


def _identifier(value):
    return isinstance(value, str) and 0 < len(value) <= 256 and not any(ord(c) < 32 for c in value)


class InteractionBridge:
    """Install before opening new sockets; reload live adapters when requested.

    ``reconnect_required`` contains adapters whose already connected sessions
    did not subscribe to interactions. Their manager can reload them normally.
    No platform configuration or SDK/core file is changed.
    """

    def __init__(self, context, transport):
        self.context = context
        self.transport = transport
        self.reconnect_required = []
        self._enabled = []
        self._seen = OrderedDict()
        self._installed = False

    async def initialize(self):
        if self._installed:
            return
        self._core = importlib.import_module(
            "astrbot.core.platform.sources.qqofficial.qqofficial_platform_adapter"
        )
        adapter_cls = self._core.QQOfficialPlatformAdapter
        client_cls = self._core.botClient
        self._adapter_cls, self._client_cls = adapter_cls, client_cls
        self._old_init = adapter_cls.__init__
        self._old_listener = client_cls.__dict__.get("on_interaction_create", _MISSING)
        self._previous_listener = getattr(client_cls, "on_interaction_create", None)
        bridge = self

        def adapter_init(adapter, *args, **kwargs):
            bridge._old_init(adapter, *args, **kwargs)
            bridge._enable(adapter)

        async def on_interaction_create(client, interaction):
            await bridge.handle(client, interaction)

        self._init_wrapper = adapter_init
        self._listener_wrapper = on_interaction_create
        adapter_cls.__init__ = adapter_init
        client_cls.on_interaction_create = on_interaction_create
        self._installed = True
        manager = getattr(self.context, "platform_manager", None)
        get_insts = getattr(manager, "get_insts", None)
        adapters = get_insts() if callable(get_insts) else getattr(manager, "platform_insts", ())
        for adapter in list(adapters or ()):
            if isinstance(adapter, adapter_cls):
                self._enable(adapter)
        logger.info("[OfficialCards] QQ interaction callback listener installed.")

    def _enable(self, adapter):
        if any(item[0] is adapter for item in self._enabled):
            return
        flags = adapter.intents
        client = adapter.client
        old_flag = bool(flags.interaction)
        old_intents = int(client.intents)
        self._enabled.append((adapter, old_flag, old_intents))
        flags.interaction = True
        client.intents = old_intents | INTERACTION_INTENT
        if not old_intents & INTERACTION_INTENT and getattr(client, "_connection", None) is not None:
            self.reconnect_required.append(adapter)
            logger.info("[OfficialCards] Connected QQ adapter needs a fresh connection for interaction events.")

    async def _ack(self, client, interaction_id, code):
        try:
            await asyncio.wait_for(
                client.api.on_interaction_result(interaction_id=interaction_id, code=code),
                timeout=4.0,
            )
            return True
        except Exception as exc:
            logger.warning(f"[OfficialCards] QQ interaction acknowledgement failed ({type(exc).__name__}).")
            return False

    async def reconnect(self):
        """Use the manager's normal fresh-start path to subscribe live sockets."""
        manager = getattr(self.context, 'platform_manager', None)
        for adapter in list(self.reconnect_required):
            current = manager.get_insts() if callable(getattr(manager, 'get_insts', None)) else getattr(manager, 'platform_insts', ())
            if adapter not in current:
                continue
            await manager.reload(adapter.config)
            logger.info('[OfficialCards] QQ official connection restarted with interaction intent.')
        self.reconnect_required.clear()

    def _reserve(self, platform_id, interaction_id):
        now = time.monotonic()
        while self._seen and (next(iter(self._seen.values())) <= now - 300 or len(self._seen) >= 2048):
            self._seen.popitem(last=False)
        key = (platform_id, interaction_id)
        if key in self._seen:
            return False
        self._seen[key] = now
        return True

    async def handle(self, client, interaction):
        interaction_id = _field(interaction, "id")
        data = _field(interaction, "data", {})
        if _field(interaction, "type") != 11 or _field(data, "type") != 11:
            if self._previous_listener:
                await self._previous_listener(client, interaction)
            return
        if not _identifier(interaction_id):
            return
        adapter = getattr(client, "platform", None)
        if not isinstance(adapter, self._adapter_cls):
            await self._ack(client, interaction_id, 1)
            return
        resolved = _field(data, "resolved", {})
        token = _field(resolved, "button_data")
        if not isinstance(token, str) or not token.startswith("oc:"):
            if self._previous_listener:
                await self._previous_listener(client, interaction)
            return
        scene = _field(interaction, "scene")
        chat_type = _field(interaction, "chat_type")
        expected_scene = {1: "group", 2: "c2c"}.get(chat_type)
        scene = scene or expected_scene
        if scene not in ("group", "c2c") or (chat_type is not None and scene != expected_scene):
            await self._ack(client, interaction_id, 1)
            return
        if scene == "group":
            session = _field(interaction, "group_openid")
            sender = _field(interaction, "group_member_openid")
        else:
            sender = session = _field(interaction, "user_openid")
        if not (_identifier(session) and _identifier(sender) and isinstance(token, str)
                and token.startswith("oc:") and len(token) <= 128):
            await self._ack(client, interaction_id, 1)
            return
        platform_id = adapter.meta().id
        command = self.transport.callback_actions.resolve(
            token, platform_id=platform_id, scene=scene, session=session, sender=sender,
        )
        if not isinstance(command, str) or not command.strip() or len(command) > 512:
            await self._ack(client, interaction_id, 1)
            return
        command = route_menu_command(command)
        reply_event_id = _field(interaction, "event_id")
        if not _identifier(reply_event_id):
            logger.warning("[OfficialCards] QQ button callback missing reply event ID; command not dispatched.")
            await self._ack(client, interaction_id, 1)
            return
        if not self._reserve(platform_id, interaction_id):
            await self._ack(client, interaction_id, 3)
            return
        # ACK takes the inner interaction id. Sending a passive message instead
        # takes the outer dispatch-envelope id preserved as botpy.event_id.
        if not await self._ack(client, interaction_id, 0):
            return
        try:
            event = await self._event(adapter, client, scene, session, sender, command, interaction_id, reply_event_id)
            # The action was resolved for this exact actor and destination.
            # Its locally stored send receipt is the only withdrawal target.
            event.set_extra(CLICKED_CARD_KEY, token)
            adapter.commit_event(event)
            logger.info(f"[OfficialCards] QQ button callback queued ({scene}).")
        except Exception as exc:
            logger.warning(f"[OfficialCards] QQ button callback dispatch failed ({type(exc).__name__}).")

    async def _event(self, adapter, client, scene, session, sender, command, interaction_id, reply_event_id):
        payload = {"id": "interaction:" + interaction_id, "content": command, "attachments": [], "mentions": []}
        if scene == "group":
            payload.update(group_openid=session, author={"member_openid": sender})
            message = self._core.PatchedGroupMessage(client.api, reply_event_id, payload)
            message_type = self._core.MessageType.GROUP_MESSAGE
        else:
            payload["author"] = {"user_openid": sender}
            message = self._core.PatchedC2CMessage(client.api, reply_event_id, payload)
            message_type = self._core.MessageType.FRIEND_MESSAGE
        abm = await adapter._parse_from_qqofficial(
            message, message_type, force_group_mention=scene == "group",
        )
        abm.session_id = session
        if scene == "group":
            abm.group_id = session
        adapter.remember_session_scene(session, "group" if scene == "group" else "friend")
        event = adapter.create_event(abm)
        event.set_extra(INTERACTION_EVENT_KEY, reply_event_id)
        # In AstrBot 4.28 this setter is a suppression flag: True forbids the
        # default LLM fallback. Menu clicks must only run the selected handler.
        event.should_call_llm(True)
        # Deliberately bypass botClient._commit: callback ids are not message ids
        # and must never replace the last real incoming message in session cache.
        return event

    def close(self):
        if not self._installed:
            return
        if self._adapter_cls.__init__ is self._init_wrapper:
            self._adapter_cls.__init__ = self._old_init
        if self._client_cls.__dict__.get("on_interaction_create") is self._listener_wrapper:
            if self._old_listener is _MISSING:
                delattr(self._client_cls, "on_interaction_create")
            else:
                self._client_cls.on_interaction_create = self._old_listener
        for adapter, old_flag, old_intents in self._enabled:
            adapter.intents.interaction = old_flag
            # Remove only the bit introduced by this bridge, preserving others.
            if not old_intents & INTERACTION_INTENT:
                adapter.client.intents &= ~INTERACTION_INTENT
        self._enabled.clear()
        self.reconnect_required.clear()
        self._seen.clear()
        self._installed = False
