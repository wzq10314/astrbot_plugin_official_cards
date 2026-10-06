"""Callback identity, authorization, acknowledgement and lifecycle contracts."""
import asyncio
import importlib.util
import logging
import types
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

import test_transport as _platform_fixtures


SPEC = importlib.util.spec_from_file_location(
    "astrbot_plugin_official_cards._interactions_test", Path(__file__).resolve().parents[1] / "interactions.py"
)
interactions = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(interactions)


class InteractionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        # Other isolated test modules stub astrbot.api; use a complete logger
        # independent of test discovery order for failure-path assertions.
        logger_patch = patch.object(interactions, "logger", logging.getLogger(__name__))
        logger_patch.start()
        self.addCleanup(logger_patch.stop)
        self.trace = []
        trace = self.trace

        class Client:
            def __init__(self):
                self.intents = 1
                self._connection = None
                self.api = types.SimpleNamespace(on_interaction_result=AsyncMock(side_effect=self.ack))

            async def ack(self, **values):
                trace.append(("ack", values))

        class Message:
            def __init__(self, api, event_id, data):
                self.event_id, self.raw_data = event_id, data
                self.id, self.content = data["id"], data["content"]
                self.author = types.SimpleNamespace(**data["author"])
                self.group_openid = data.get("group_openid")

        class Event:
            def __init__(self, abm):
                self.message_obj, self.extra = abm, {}

            def set_extra(self, name, value):
                self.extra[name] = value

            def should_call_llm(self, value):
                self.call_llm = value

        class Adapter:
            def __init__(self):
                self.intents = types.SimpleNamespace(interaction=False)
                self.client = Client()
                self.client.platform = self
                self.events, self.scenes = [], {}
                self.message_cache = {"group-original": "last-real-message"}

            def meta(self):
                return types.SimpleNamespace(id="platform-1")

            async def _parse_from_qqofficial(self, message, message_type, force_group_mention=False):
                trace.append(("parse", force_group_mention))
                sender = getattr(message.author, "member_openid", None) or message.author.user_openid
                return types.SimpleNamespace(raw_message=message, sender=types.SimpleNamespace(user_id=sender),
                                             message_id=message.id, message_str=message.content, type=message_type)

            def remember_session_scene(self, key, value):
                self.scenes[key] = value

            def create_event(self, abm):
                return Event(abm)

            def commit_event(self, event):
                trace.append(("commit", event))
                self.events.append(event)

        self.Adapter, self.Client = Adapter, Client
        self.core = types.SimpleNamespace(QQOfficialPlatformAdapter=Adapter, botClient=Client,
                                          PatchedGroupMessage=Message, PatchedC2CMessage=Message,
                                          MessageType=types.SimpleNamespace(GROUP_MESSAGE="group", FRIEND_MESSAGE="friend"))
        self.adapter = Adapter()
        self.context = types.SimpleNamespace(platform_manager=types.SimpleNamespace(get_insts=lambda: [self.adapter]))
        self.resolutions = []
        self.selected_command = "/功能菜单"

        def resolve(token, **scope):
            self.resolutions.append((token, scope))
            if token == "oc:known" and scope["sender"] == "clicker":
                return self.selected_command

        self.transport = types.SimpleNamespace(callback_actions=types.SimpleNamespace(resolve=resolve))
        self.bridge = interactions.InteractionBridge(self.context, self.transport)
        with patch.object(interactions.importlib, "import_module", return_value=self.core):
            await self.bridge.initialize()

    async def asyncTearDown(self):
        self.bridge.close()

    def callback(self, **changes):
        result = dict(id="ack-inner-id", event_id="reply-outer-event", type=11, scene="group", chat_type=1,
                      group_openid="group-original", group_member_openid="clicker",
                      data=types.SimpleNamespace(type=11, resolved=types.SimpleNamespace(button_data="oc:known")))
        result.update(changes)
        return types.SimpleNamespace(**result)

    async def test_group_click_ack_then_original_pipeline_as_clicker(self):
        await self.adapter.client.on_interaction_create(self.callback())
        self.assertEqual([item[0] for item in self.trace], ["ack", "parse", "commit"])
        event = self.adapter.events[0]
        self.assertEqual(event.extra[interactions.INTERACTION_EVENT_KEY], "reply-outer-event")
        self.assertEqual(event.message_obj.raw_message.event_id, "reply-outer-event")
        self.adapter.client.api.on_interaction_result.assert_awaited_once_with(interaction_id="ack-inner-id", code=0)
        self.assertTrue(event.call_llm)
        self.assertEqual(event.message_obj.sender.user_id, "clicker")
        self.assertEqual(event.message_obj.group_id, "group-original")
        self.assertEqual(event.message_obj.session_id, "group-original")
        self.assertEqual(event.message_obj.message_str, "/功能菜单")
        self.assertEqual(self.adapter.message_cache, {"group-original": "last-real-message"})
        self.assertFalse(hasattr(event, "is_admin"))
        self.assertTrue(self.trace[1][1])

    async def test_c2c_uses_user_openid_not_resolved_or_group_identity(self):
        await self.bridge.handle(self.adapter.client, self.callback(scene="c2c", chat_type=2, user_openid="clicker"))
        event = self.adapter.events[0]
        self.assertEqual(event.message_obj.session_id, "clicker")
        self.assertEqual(event.message_obj.type, "friend")
        self.assertEqual(event.extra[interactions.INTERACTION_EVENT_KEY], "reply-outer-event")
        self.assertEqual(event.message_obj.raw_message.event_id, "reply-outer-event")
        self.assertTrue(event.call_llm)
        self.assertEqual(self.adapter.scenes, {"clicker": "friend"})
        self.assertEqual(self.resolutions[0][1], dict(platform_id="platform-1", scene="c2c", session="clicker", sender="clicker"))

    async def test_legacy_category_callbacks_route_only_after_owner_authorization(self):
        destinations = {"光遇": "/光遇帮助", "签到": "/签到帮助", "王者": "#王者帮助",
                        "音乐": "#R帮助", "pIXiv": "/pixiv帮助", "PICA": "/pica帮助", "jm": "/jm帮助"}
        actual_route = interactions.route_menu_command
        for index, (category, target) in enumerate(destinations.items()):
            for scene in ("group", "c2c"):
                with self.subTest(category=category, scene=scene):
                    self.selected_command = "/功能菜单 " + category
                    identity = {"id": f"route-{index}-{scene}"}
                    if scene == "c2c":
                        identity.update(scene="c2c", chat_type=2, user_openid="clicker")
                    unauthorized = dict(identity)
                    unauthorized["group_member_openid" if scene == "group" else "user_openid"] = "intruder"
                    before = len(self.adapter.events)
                    with patch.object(interactions, "route_menu_command", wraps=actual_route) as route:
                        await self.bridge.handle(self.adapter.client, self.callback(**unauthorized))
                        route.assert_not_called()
                        self.assertEqual(len(self.adapter.events), before)
                        self.assertEqual(self.adapter.client.api.on_interaction_result.call_args.kwargs["code"], 1)
                        await self.bridge.handle(self.adapter.client, self.callback(**identity))
                        route.assert_called_once_with(self.selected_command)
                    self.assertEqual(len(self.adapter.events), before + 1)
                    queued = self.adapter.events[-1]
                    self.assertEqual(queued.message_obj.message_str, target)
                    self.assertEqual(queued.message_obj.raw_message.content, target)
                    self.assertEqual(queued.message_obj.sender.user_id, "clicker")
                    self.assertEqual(queued.message_obj.session_id, "group-original" if scene == "group" else "clicker")
                    self.assertEqual(queued.extra[interactions.INTERACTION_EVENT_KEY], "reply-outer-event")
                    self.assertTrue(queued.call_llm)
        self.assertEqual(self.adapter.message_cache, {"group-original": "last-real-message"})

    async def test_duplicate_concurrent_callbacks_execute_once(self):
        await asyncio.gather(*(self.bridge.handle(self.adapter.client, self.callback()) for _ in range(2)))
        self.assertEqual(len(self.adapter.events), 1)
        self.assertEqual(sorted(call.kwargs["code"] for call in self.adapter.client.api.on_interaction_result.call_args_list), [0, 3])

    async def test_invalid_scope_or_unknown_token_does_not_execute(self):
        variants = [dict(group_member_openid="someone-else"), dict(scene="c2c", chat_type=1),
                    dict(group_member_openid=""), dict(scene="guild", chat_type=0),
                    dict(data={"type": 11, "resolved": {"button_data": "oc:expired"}})]
        for index, values in enumerate(variants):
            await self.bridge.handle(self.adapter.client, self.callback(id=f"invalid-{index}", **values))
        self.assertEqual(self.adapter.events, [])
        self.assertTrue(all(call.kwargs["code"] == 1 for call in self.adapter.client.api.on_interaction_result.call_args_list))

    async def test_ack_failure_does_not_execute(self):
        self.adapter.client.api.on_interaction_result.side_effect = TimeoutError()
        await self.bridge.handle(self.adapter.client, self.callback())
        self.assertEqual(self.adapter.events, [])

    async def test_missing_reply_id_does_not_reuse_ack_id_or_dispatch(self):
        for value in (None, "", "bad\nvalue"):
            await self.bridge.handle(self.adapter.client, self.callback(event_id=value))
        self.assertEqual(self.adapter.events, [])
        self.assertTrue(all(call.kwargs == {"interaction_id": "ack-inner-id", "code": 1}
                            for call in self.adapter.client.api.on_interaction_result.call_args_list))

    async def test_live_and_future_intents_restore_and_keep_other_bits(self):
        self.assertTrue(self.adapter.intents.interaction)
        self.assertEqual(self.adapter.client.intents, 1 | interactions.INTERACTION_INTENT)
        future = self.Adapter()
        self.assertTrue(future.intents.interaction)
        future.client.intents |= 8
        self.bridge.close()
        self.assertFalse(future.intents.interaction)
        self.assertEqual(future.client.intents, 9)
        self.assertNotIn("on_interaction_create", self.Client.__dict__)
        fresh = self.Adapter()
        self.assertFalse(fresh.intents.interaction)

    async def test_connected_adapters_report_need_for_fresh_identify(self):
        self.bridge.close()
        self.adapter.client._connection = object()
        with patch.object(interactions.importlib, "import_module", return_value=self.core):
            await self.bridge.initialize()
        self.assertEqual(self.bridge.reconnect_required, [self.adapter])

    async def test_reconnect_uses_manager_fresh_start_and_skips_stale_adapters(self):
        self.adapter.config = {'id': 'official-test'}
        stale = self.Adapter()
        self.context.platform_manager.reload = AsyncMock()
        self.bridge.reconnect_required = [stale, self.adapter]
        await self.bridge.reconnect()
        self.context.platform_manager.reload.assert_awaited_once_with(self.adapter.config)
        self.assertEqual(self.bridge.reconnect_required, [])

    async def test_non_button_event_retains_previous_listener(self):
        self.bridge.close()
        previous = AsyncMock()
        self.Client.on_interaction_create = previous
        with patch.object(interactions.importlib, "import_module", return_value=self.core):
            await self.bridge.initialize()
        callback = self.callback(type=12)
        await self.bridge.handle(self.adapter.client, callback)
        previous.assert_awaited_once_with(self.adapter.client, callback)
        self.assertEqual(self.adapter.events, [])
        self.bridge.close()
        self.assertIs(self.Client.on_interaction_create, previous)

    async def test_other_plugins_button_retains_previous_listener(self):
        self.bridge.close()
        previous = AsyncMock()
        self.Client.on_interaction_create = previous
        with patch.object(interactions.importlib, "import_module", return_value=self.core):
            await self.bridge.initialize()
        callback = self.callback(data={"type": 11, "resolved": {"button_data": "another-plugin:action"}})
        await self.bridge.handle(self.adapter.client, callback)
        previous.assert_awaited_once_with(self.adapter.client, callback)
        self.assertEqual(self.adapter.events, [])
        self.adapter.client.api.on_interaction_result.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
