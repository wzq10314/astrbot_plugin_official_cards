"""Original help routes retain the normal pipeline and real message identity."""
import asyncio
import importlib
import types
import unittest
from unittest.mock import patch

import test_transport as fixtures


routes = importlib.import_module("astrbot_plugin_official_cards.menu_routes")


class Mention:
    def __init__(self, qq):
        self.qq = qq


class Event:
    def __init__(self, message):
        self.message_obj = message
        self.message_str = message.message_str
        self.extras = {}
        self.role = "member"
        self.plugins_name = None
        self.stopped = False
        self.send_buffer = None

    def get_platform_id(self): return "qq-test"
    def get_platform_name(self): return "qq_official"
    def get_extra(self, name, default=None): return self.extras.get(name, default)
    def set_extra(self, name, value): self.extras[name] = value
    def should_call_llm(self, value): self.call_llm = value


class Adapter:
    def __init__(self, platform_id="qq-test"):
        self.platform_id = platform_id
        self.events = []
        self.created = []

    def meta(self): return types.SimpleNamespace(id=self.platform_id, name="qq_official")

    def create_event(self, message):
        self.created.append(message)
        return Event(message)

    def commit_event(self, event): self.events.append(event)


class MenuRouteTests(unittest.TestCase):
    def setUp(self):
        mention_patch = patch.object(routes, "At", Mention)
        mention_patch.start()
        self.addCleanup(mention_patch.stop)
        self.adapter = Adapter()
        self.context = types.SimpleNamespace(platform_manager=types.SimpleNamespace(
            get_insts=lambda: [Adapter("other-platform"), self.adapter]))
        self.raw = types.SimpleNamespace(group_openid="real-group", event_id="sdk-envelope")
        self.source = types.SimpleNamespace(
            message_str="/功能菜单 JM", message=[Mention("bot-id"), fixtures.Plain("/功能菜单 JM")],
            type=types.SimpleNamespace(name="GROUP_MESSAGE"), self_id="bot-id",
            session_id="real-group", group_id="real-group", message_id="real-incoming-message",
            sender=types.SimpleNamespace(user_id="actual-clicker"), raw_message=self.raw)
        self.event = Event(self.source)
        self.event.bot = types.SimpleNamespace(platform=self.adapter)

    def test_static_help_routes_and_case_insensitive_category_aliases(self):
        expected = {"光遇": "/光遇帮助", "签到": "/签到帮助", "王者": "#王者帮助",
                    "音乐": "#R帮助", "Pixiv": "/pixiv帮助", "Pica": "/pica帮助", "JM": "/jm帮助"}
        self.assertEqual(routes.HELP_ROUTES, expected)
        for category, command in expected.items():
            self.assertEqual(routes.original_help_command(category), command)
        for category, command in (("sKy", "/光遇帮助"), ("GET_PX", "/签到帮助"),
                                  ("gloryofkings", "#王者帮助"), ("RCONSOLE", "#R帮助"),
                                  ("pIXiv", "/pixiv帮助"), ("piCA", "/pica帮助"), (" jm ", "/jm帮助")):
            self.assertEqual(routes.original_help_command(category), command)
        for category in ("", "小镇", "扩展", "JM 文字", "JM\n", "JM\r/pica下载", None):
            self.assertIsNone(routes.original_help_command(category))

    def test_only_exact_old_category_commands_are_rewritten(self):
        for prefix in ("/", "#", ""):
            for menu in ("功能菜单", "官方菜单"):
                self.assertEqual(routes.route_menu_command(prefix + menu + " jm"), "/jm帮助")
        for command in ("/功能菜单", "/功能菜单 JM 文字", "/功能菜单 JM\n/pica下载", "#功能菜单 小镇",
                        "/pixiv帮助", "/jm下载 123", "/foo功能菜单 JM"):
            self.assertEqual(routes.route_menu_command(command), command)

    def test_group_requeue_preserves_destination_and_sender_without_copying_handler_state(self):
        self.event.role = "admin"
        self.event.stopped = True
        self.event.plugins_name = ["only-original-plugins"]
        self.event.extras.update({"qqofficial_interaction_event_id": "outer-reply-id",
                                 "_api_key_allow_admin_role": False,
                                 "activated_handlers": ["old-menu-handler"], "parsed_params": {"category": "JM"},
                                 "qq_official_card": {"title": "old category"}})
        original_parts = list(self.source.message)
        self.assertTrue(routes.queue_original_help(self.context, self.event, "JM"))
        self.assertEqual(len(self.adapter.events), 1)
        queued = self.adapter.events[0]
        self.assertIsNot(queued, self.event)
        self.assertIsNot(queued.message_obj, self.source)
        self.assertIs(queued.message_obj.raw_message, self.raw)
        self.assertIs(queued.message_obj.sender, self.source.sender)
        self.assertEqual(queued.message_obj.message_id, "real-incoming-message")
        self.assertEqual(queued.message_obj.session_id, "real-group")
        self.assertEqual(queued.message_obj.group_id, "real-group")
        self.assertEqual(queued.message_str, "/jm帮助")
        self.assertEqual(queued.message_obj.message[-1].text, "/jm帮助")
        self.assertEqual(queued.message_obj.message[0].qq, "bot-id")
        self.assertIsNot(queued.message_obj.message[0], original_parts[0])
        self.assertEqual(self.source.message, original_parts)
        self.assertEqual(self.source.message_str, "/功能菜单 JM")
        self.assertEqual(self.source.message[-1].text, "/功能菜单 JM")
        self.assertEqual(queued.role, "member", "pipeline must recalculate administrator status")
        self.assertFalse(queued.stopped)
        self.assertIsNone(queued.send_buffer)
        self.assertTrue(queued.is_wake)
        self.assertTrue(queued.is_at_or_wake_command)
        self.assertTrue(queued.call_llm)
        self.assertEqual(queued.plugins_name, self.event.plugins_name)
        self.assertIsNot(queued.plugins_name, self.event.plugins_name)
        self.assertEqual(queued.extras["qqofficial_interaction_event_id"], "outer-reply-id")
        self.assertIs(queued.extras["_api_key_allow_admin_role"], False)
        for old_key in ("activated_handlers", "parsed_params", "qq_official_card"):
            self.assertNotIn(old_key, queued.extras)

    def test_missing_group_bot_mention_is_added_without_preserving_input_attachments(self):
        self.source.message = [Mention("another-member"), fixtures.Plain("old text"), fixtures.Image("attachment")]
        self.assertTrue(routes.queue_original_help(self.context, self.event, "Pixiv"))
        parts = self.adapter.events[0].message_obj.message
        self.assertEqual([item.qq for item in parts if isinstance(item, Mention)], ["bot-id", "another-member"])
        self.assertEqual([item.text for item in parts if isinstance(item, fixtures.Plain)], ["/pixiv帮助"])
        self.assertFalse(any(isinstance(item, fixtures.Image) for item in parts))

    def test_private_requeue_keeps_private_identity_and_empty_plugin_allowlist(self):
        self.source.type.name = "FRIEND_MESSAGE"
        self.source.group_id = ""
        self.source.session_id = "actual-clicker"
        self.source.self_id = ""
        self.source.message = [fixtures.Plain("/功能菜单 pica")]
        self.event.plugins_name = []
        self.assertTrue(routes.queue_original_help(self.context, self.event, "PICA"))
        queued = self.adapter.events[0]
        self.assertEqual(queued.message_obj.session_id, "actual-clicker")
        self.assertEqual(queued.message_obj.type.name, "FRIEND_MESSAGE")
        self.assertEqual(len(queued.message_obj.message), 1)
        self.assertEqual(queued.plugins_name, [])
        self.assertNotIn("qqofficial_interaction_event_id", queued.extras)

    def test_invalid_route_platform_or_scene_never_enters_pipeline(self):
        self.assertFalse(routes.queue_original_help(self.context, self.event, "unsupported"))
        self.source.type.name = "OTHER_MESSAGE"
        self.assertFalse(routes.queue_original_help(self.context, self.event, "JM"))
        self.source.type.name = "GROUP_MESSAGE"
        self.source.self_id = ""
        self.assertFalse(routes.queue_original_help(self.context, self.event, "JM"))
        self.source.self_id = "bot-id"
        self.event.get_platform_name = lambda: "aiocqhttp"
        self.assertFalse(routes.queue_original_help(self.context, self.event, "JM"))
        self.event.get_platform_name = lambda: "qq_official"
        self.event.get_platform_id = lambda: "wrong-platform"
        self.assertFalse(routes.queue_original_help(self.context, self.event, "JM"))
        self.assertEqual(self.adapter.events, [])

    def test_one_source_event_can_only_enqueue_once_and_does_not_stop_itself(self):
        self.assertTrue(routes.queue_original_help(self.context, self.event, "JM"))
        self.assertTrue(routes.queue_original_help(self.context, self.event, "jm"))
        self.assertFalse(routes.queue_original_help(self.context, self.event, "pica"))
        self.assertEqual(len(self.adapter.events), 1)
        self.assertFalse(self.event.stopped)

    def test_queue_failure_is_reported_without_claiming_success(self):
        def full(event):
            raise asyncio.QueueFull()

        self.adapter.commit_event = full
        self.assertFalse(routes.queue_original_help(self.context, self.event, "JM"))
        self.assertIsNone(self.event.get_extra(routes._ROUTED_KEY))
        self.assertFalse(self.adapter.events)


if __name__ == "__main__":
    unittest.main()
