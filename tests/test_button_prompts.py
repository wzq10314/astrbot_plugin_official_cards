import importlib
import unittest

from test_keyboard_pages import Event
import test_transport as fixtures


prompts = importlib.import_module("astrbot_plugin_official_cards.button_prompts")


class ButtonPromptTests(unittest.TestCase):
    def test_usage_is_friendly_and_has_no_action_dispatch(self):
        event, store = Event(), prompts.ButtonPromptStore()
        expected = {
            "#点歌": "#点歌 晴天", "#rparse": "#rparse BV1xx411c7mD",
            "/steam price": "/steam price 黑神话：悟空", "/lmem search": "/lmem search 偏好 5",
            "#王者对比": "#王者对比 123456789", "#查战力": "#查战力 孙悟空",
            "#查战绩": "#查战绩 妲己", "#查皮肤": "#查皮肤 百里守约",
            "#缺皮肤": "#缺皮肤 妲己", "#英雄攻略": "#英雄攻略 孙悟空",
            "#绑定营地": "#绑定营地 123456789", "#切换营地": "#切换营地2",
            "#删除营地": "#删除营地2",
        }
        for command, example in expected.items():
            with self.subTest(command=command):
                issued = store.create("按钮名称", command + " ", event)
                self.assertRegex(issued, r"^/按钮用法 [A-Za-z0-9_-]{24}$")
                text = store.get(issued.split()[1], event)
                self.assertIn("按钮名称", text)
                self.assertIn("命令格式", text)
                self.assertIn(example, text)
                self.assertIn("未执行操作", text)
        self.assertEqual(event.bot.api.calls, [])
        self.assertFalse(event.marked_sent)

    def test_scope_checks_platform_scene_session_sender_and_admin(self):
        event, store = Event(admin=True), prompts.ButtonPromptStore()
        token = store.create("删除营地", "#删除营地2", event).split()[1]
        for other in (Event(platform="elsewhere", admin=True), Event(session="elsewhere", admin=True),
                      Event(sender="bob", admin=True), Event(admin=False)):
            self.assertIsNone(store.get(token, other))
        other = Event(admin=True)
        other.message_obj.raw_message = fixtures.C2CMessage()
        self.assertIsNone(store.get(token, other))
        self.assertIsNotNone(store.get(token, Event(admin=True)))

    def test_expiry_is_not_extended_by_get_and_capacity_is_bounded(self):
        now = [0.0]
        store = prompts.ButtonPromptStore(ttl=5, max_entries=2, clock=lambda: now[0])
        event = Event()
        first = store.create("一", "#查战力", event).split()[1]
        second = store.create("二", "#查皮肤", event).split()[1]
        third = store.create("三", "#查战绩", event).split()[1]
        self.assertEqual(len(store.entries), 2)
        self.assertIsNone(store.get(first, event))
        now[0] = 4.0
        self.assertIsNotNone(store.get(second, event))
        now[0] = 5.0
        self.assertIsNone(store.get(second, event))
        self.assertIsNone(store.get(third, event))
        self.assertFalse(store.entries)
        store.create("一", "#查战力", event)
        store.clear()
        self.assertFalse(store.entries)
        capped = prompts.ButtonPromptStore(ttl=7200, max_entries=2048)
        self.assertEqual((capped.ttl, capped.max_entries), (3600, 1024))

    def test_no_owner_and_invalid_input_do_not_issue_tokens(self):
        store = prompts.ButtonPromptStore()
        for event in (None, object(), Event(sender=""), Event(session=""), Event(platform="")):
            self.assertIsNone(store.create("按钮", "#查战力", event))
        event = Event()
        for command in ("", " ", None, [], "x" * 513, "#查战力\n#删除营地1", "#查战力\r",
                        "#查战力\t", "#查战力\x00", "#查战力\x7f", "#查战力\u202e", "#查战力\u2028"):
            self.assertIsNone(store.create("按钮", command, event))
        for label in ("", "x" * 513, "按钮\n注入", None):
            self.assertIsNone(store.create(label, "#查战力", event))
        for token in (None, [], "", "not-a-token", "x" * 10000):
            self.assertIsNone(store.get(token, event))
        self.assertFalse(store.entries)

    def test_generic_command_is_an_immutable_inert_snapshot(self):
        event, store = Event(), prompts.ButtonPromptStore()
        original = {"label": "未知功能", "command": "/未知参数 123"}
        token = store.create(original["label"], original["command"], event).split()[1]
        original.update(label="已修改", command="/不同命令")
        text = store.get(token, event)
        self.assertIn("未知功能", text)
        self.assertIn("/未知参数 123", text)
        self.assertNotIn("/不同命令", text)
        self.assertIn("确认完整命令后再手动发送", text)
        self.assertIn("未执行操作", text)
        self.assertEqual(event.bot.api.calls, [])

    def test_markdown_label_is_escaped_and_backticks_cannot_break_code_fence(self):
        text = prompts.usage_text("[点我](https://example.test)<b>*", "/未知 ```注入``` **内容**")
        self.assertIn(r"\[点我\]\(https://example", text)
        self.assertIn("&lt;b&gt;", text)
        self.assertNotIn("<b>", text)
        self.assertIn("````text\n/未知 ```注入``` **内容**\n````", text)
        self.assertIsNone(prompts.usage_text("按钮", "/未知\n```\n注入"))


if __name__ == "__main__":
    unittest.main()
