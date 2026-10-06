"""Pagination keeps every action reachable without sharing an owner's menu."""
import ast
import importlib
import types
import unittest
from pathlib import Path

import test_transport as fixtures


pages = importlib.import_module("astrbot_plugin_official_cards.keyboard_pages")
support = importlib.import_module("astrbot_plugin_official_cards.support")
transport = fixtures.transport


class Event(fixtures.Event):
    def __init__(self, chain=None, api=None, *, platform="official-test", session="group-openid", sender="alice", admin=False):
        super().__init__(chain or fixtures.Chain([]), api or fixtures.API())
        self.platform, self.session, self.sender, self.admin = platform, session, sender, admin
        self.extras = {}

    def get_platform_id(self): return self.platform
    def get_platform_name(self): return "qq_official"
    def get_session_id(self): return self.session
    def get_sender_id(self): return self.sender
    def is_admin(self): return self.admin
    def get_extra(self, key, default=None): return self.extras.get(key, default)
    def set_extra(self, key, value): self.extras[key] = value
    def plain_result(self, text): return Result(text)


class Result(fixtures.Chain):
    def __init__(self, text): super().__init__([fixtures.Plain(text)])
    def use_t2i(self, flag): return self
    def use_markdown(self, flag):
        self.use_markdown_ = flag
        return self


def dynamic_buttons(count):
    return [{"label": f"完整操作名称{index}", "command": f"#切换账号 {index}", "enter": True}
            for index in range(count)]


def actions(keyboard):
    return [button for row in keyboard["content"]["rows"] for button in row["buttons"]]


def page_handler():
    source = Path(__file__).resolve().parents[1] / "main.py"
    tree = ast.parse(source.read_text(encoding="utf-8-sig"))
    plugin = next(item for item in tree.body if isinstance(item, ast.ClassDef))
    method = next(item for item in plugin.body if isinstance(item, ast.AsyncFunctionDef) and item.name == "show_keyboard_page")
    method.decorator_list = []
    namespace = {"AstrMessageEvent": Event, "is_qq_official": support.is_qq_official,
                 "set_card_hint": support.set_card_hint, "HOME_BUTTON": pages.HOME_BUTTON,
                 "PAGE_HINT_KEY": pages.PAGE_HINT_KEY}
    exec(compile(ast.fix_missing_locations(ast.Module(body=[method], type_ignores=[])), str(source), "exec"), namespace)
    return namespace[method.name]


class KeyboardPageTests(unittest.TestCase):
    def test_layout_uses_two_columns_and_preserves_regular_labels(self):
        label = "这是应当完整保留的动态按钮名称"
        buttons = dynamic_buttons(10)
        buttons[0]["label"] = label
        keyboard = transport.build_keyboard(buttons)
        self.assertEqual([len(row["buttons"]) for row in keyboard["content"]["rows"]], [2] * 5)
        self.assertEqual(actions(keyboard)[0]["render_data"]["label"], label)
        self.assertTrue(all(not button["action"]["enter"] for button in actions(keyboard)))
        buttons[0]["label"] = "长" * 41
        self.assertEqual(len(actions(transport.build_keyboard(buttons))[0]["render_data"]["label"]), 40)
        with self.assertRaisesRegex(ValueError, "pagination"):
            transport.build_keyboard(dynamic_buttons(11))

    def test_large_menus_keep_every_action_reachable_exactly_once(self):
        for count in (14, 15, 25, 26, 49, 256):
            with self.subTest(count=count):
                store, event = pages.KeyboardPageStore(), Event()
                original = transport.normalize_buttons(dynamic_buttons(count))
                first = store.create(original, event)
                seen = []
                for number in range(1, first.total + 1):
                    page = store.get_page(first.token, number, event)
                    keyboard = transport.build_keyboard(page.buttons, navigation_commands=page.navigation_commands)
                    self.assertLessEqual(len(keyboard["content"]["rows"]), 5)
                    self.assertTrue(all(len(row["buttons"]) <= 2 for row in keyboard["content"]["rows"]))
                    last_row = keyboard["content"]["rows"][-1]["buttons"]
                    self.assertTrue(all(button["action"]["data"] in page.navigation_commands for button in last_row))
                    self.assertEqual(len(last_row), len(page.navigation_commands))
                    for button in actions(keyboard):
                        action = button["action"]
                        if action["data"] in page.navigation_commands:
                            self.assertTrue(action["enter"])
                        else:
                            self.assertFalse(action["enter"])
                            seen.append(action["data"])
                self.assertEqual(seen, [item["command"] for item in original])
                self.assertEqual(len(seen), count)

    def test_card_snapshot_keeps_original_content_and_image_on_every_page(self):
        now = [1.0]
        store = pages.KeyboardPageStore(ttl=10, clock=lambda: now[0])
        owner = Event()
        image_url = "https://example.test/api/file/owned-help-image"
        content = f"## 王者帮助\n\n原始帮助说明\n\n![帮助图]({image_url})"
        image_tokens = ["owned-help-image"]
        original = dynamic_buttons(25)
        first = store.create(original, owner, card_content=content, image_tokens=image_tokens)
        image_tokens[0] = "changed-token"
        original[0]["label"] = "changed-label"
        for number in (2, 4, 1):
            selected = store.get_page(first.token, number, owner)
            self.assertEqual(selected.card_content, content)
            self.assertEqual(selected.image_tokens, ("owned-help-image",))
            self.assertEqual(selected.text, f"{content}\n\n按钮第 {number}/4 页")
            self.assertEqual(selected.text.count(image_url), 1)
            self.assertNotIn("操作菜单", selected.text)
            self.assertNotIn("#切换账号", selected.text)
        self.assertNotEqual(store.get_page(first.token, 1, owner).buttons[0]["label"], "changed-label")
        self.assertIsNone(store.get_page(first.token, 2, Event(sender="bob")))
        now[0] = 10.0
        self.assertIsNotNone(store.get_page(first.token, 2, owner))
        now[0] = 11.0
        self.assertIsNone(store.get_page(first.token, 1, owner))

    def test_card_snapshot_limits_are_bounded_without_truncating_content(self):
        store, owner, buttons = pages.KeyboardPageStore(), Event(), dynamic_buttons(15)
        content = "x" * pages.MAX_CARD_CONTENT_CHARS
        self.assertEqual(store.create(buttons, owner, card_content=content).card_content, content)
        self.assertIsNone(store.create(buttons, owner, card_content=content + "x"))
        self.assertIsNone(store.create(buttons, owner, card_content=None))
        self.assertIsNone(store.create(buttons, owner, image_tokens=["owned"] * (pages.MAX_IMAGE_TOKENS + 1)))
        for tokens in ("owned", (None,), ("",), ("bad\nname",), ("x" * 513,)):
            self.assertIsNone(store.create(buttons, owner, image_tokens=tokens))
        self.assertIsNone(store.create(dynamic_buttons(pages.MAX_BUTTONS + 1), owner))

    def test_root_menu_preserves_all_seventeen_categories(self):
        _, buttons = fixtures.menus.menu_page()
        event, store = Event(), pages.KeyboardPageStore()
        first = store.create(transport.normalize_buttons(buttons), event)
        commands = []
        for number in range(1, first.total + 1):
            page = store.get_page(first.token, number, event)
            commands.extend(button["command"] for button in page.buttons
                            if button["command"] not in page.navigation_commands)
        self.assertEqual(commands, [button["command"] for button in buttons])
        self.assertEqual(len(commands), 17)

    def test_scope_binds_platform_scene_session_requester_and_admin_role(self):
        store, owner = pages.KeyboardPageStore(), Event(admin=True)
        page = store.create(transport.normalize_buttons(dynamic_buttons(15)), owner)
        for event in (Event(platform="other", admin=True), Event(session="elsewhere", admin=True),
                      Event(sender="bob", admin=True), Event(admin=False)):
            self.assertIsNone(store.get_page(page.token, 2, event))
        changed_scene = Event(admin=True)
        changed_scene.message_obj.raw_message = fixtures.C2CMessage()
        self.assertIsNone(store.get_page(page.token, 2, changed_scene))
        self.assertIsNotNone(store.get_page(page.token, 2, Event(admin=True)))

    def test_only_issued_navigation_can_auto_enter(self):
        store, event = pages.KeyboardPageStore(), Event()
        page = store.create(transport.normalize_buttons(dynamic_buttons(15)), event)
        command = next(iter(page.navigation_commands))
        self.assertFalse(transport._safe_enter(command))
        forged = [{"label": "翻页", "command": command, "enter": True}]
        self.assertFalse(actions(transport.build_keyboard(forged))[0]["action"]["enter"])
        for invalid in (command + "\n/禁言 123", command + " extra", command.replace(" 2", " 3")):
            keyboard = transport.build_keyboard([{"label": "翻页", "command": invalid, "enter": True}],
                                                navigation_commands=page.navigation_commands)
            self.assertFalse(actions(keyboard)[0]["action"]["enter"])

    def test_expiry_eviction_invalid_pages_and_close_do_not_keep_snapshots(self):
        now = [1.0]
        store = pages.KeyboardPageStore(ttl=10, max_entries=2, clock=lambda: now[0])
        event, buttons = Event(), transport.normalize_buttons(dynamic_buttons(15))
        first = store.create(buttons, event)
        buttons[0]["command"] = "#changed"
        self.assertNotEqual(store.get_page(first.token, 1, event).buttons[0]["command"], "#changed")
        for invalid in (-1, 0, 3, True, "2"):
            self.assertIsNone(store.get_page(first.token, invalid, event))
        second, third = store.create(buttons, event), store.create(buttons, event)
        self.assertIsNone(store.get_page(first.token, 1, event))
        self.assertEqual(len(store.entries), 2)
        now[0] = 10.0
        self.assertIsNotNone(store.get_page(second.token, 1, event))
        now[0] = 11.0
        self.assertIsNone(store.get_page(third.token, 1, event))
        self.assertFalse(store.entries)
        store.create(buttons, event)
        store.clear()
        self.assertFalse(store.entries)

    def test_proactive_overflow_exposes_every_command_without_a_shared_token(self):
        cards = transport.CardTransport(fixtures.Publisher())
        original = dynamic_buttons(25)
        payload = cards._payload("主动通知", original, ("platform", "group", "proactive"))
        rendered = actions(payload["keyboard"])
        self.assertEqual(len(rendered), 10)
        self.assertEqual(rendered[-1]["action"]["data"], "/功能菜单")
        self.assertFalse(cards.keyboard_pages.entries)
        displayed = {button["action"]["data"] for button in rendered}
        for item in original:
            self.assertTrue(item["command"] in displayed or item["command"] in payload["markdown"]["content"])
        self.assertNotIn("/菜单翻页", payload["markdown"]["content"])


class KeyboardTransportTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.cards = transport.CardTransport(fixtures.Publisher())
        self.cards.install()

    async def asyncTearDown(self): self.cards.close()

    async def test_transport_and_handler_preserve_navigation_enter_on_derived_chunks(self):
        chain = fixtures.Chain([fixtures.Plain("王者主菜单")])
        chain.qqofficial_buttons = dynamic_buttons(25)
        event = Event(chain)
        await event._post_send_one(chain.derive(chain.chain))
        initial = actions(event.bot.api.calls[0]["keyboard"])
        navigation = initial[-1]["action"]
        self.assertTrue(navigation["enter"])
        _, token, number = navigation["data"].split()
        page_event = Event()
        plugin = types.SimpleNamespace(transport=self.cards)
        results = [result async for result in page_handler()(plugin, page_event, token, int(number))]
        self.assertEqual(len(results), 1)
        result = results[0]
        page_event.send_buffer = result
        await page_event._post_send_one(result.derive(result.chain))
        outgoing = actions(page_event.bot.api.calls[0]["keyboard"])
        self.assertEqual(len(outgoing), 10)
        self.assertEqual([button["action"]["data"] for button in outgoing[:8]],
                         [f"#切换账号 {index}" for index in range(8, 16)])
        self.assertTrue(all(not button["action"]["enter"] for button in outgoing[:8]))
        self.assertTrue(all(button["action"]["enter"] for button in outgoing[8:]))
        self.assertEqual(len(self.cards.keyboard_pages.entries), 1)
        # Core may split a reply; only its final chunk should have a keyboard.
        intermediate = self.cards._payload("前一片段", [], ("official-test", "GroupMessage", "passive"), event=page_event)
        self.assertNotIn("keyboard", intermediate)

    async def test_handler_rejects_cross_user_and_expired_and_leaves_nonofficial_alone(self):
        page = self.cards.keyboard_pages.create(transport.normalize_buttons(dynamic_buttons(15)), Event(admin=True))
        plugin, handler = types.SimpleNamespace(transport=self.cards), page_handler()
        for event, token in ((Event(sender="bob", admin=True), page.token), (Event(admin=True), "expired")):
            results = [result async for result in handler(plugin, event, token, 2)]
            self.assertEqual(len(results), 1)
            self.assertIn("重新发送帮助命令", results[0].chain[0].text)
            self.assertNotIn("#切换账号", results[0].chain[0].text)
            self.assertNotIn(pages.PAGE_HINT_KEY, event.extras)
        other = Event()
        other.get_platform_name = lambda: "aiocqhttp"
        self.assertEqual([result async for result in handler(plugin, other, page.token, 2)], [])

    async def test_handler_preserves_card_back_navigation_and_rejects_missing_images(self):
        image_url = "https://example.test/api/file/owned-help-image"
        content = f"# 王者帮助\n\n原始说明\n\n![帮助图]({image_url})"
        now = [1.0]
        self.cards.keyboard_pages = pages.KeyboardPageStore(ttl=10, clock=lambda: now[0])
        page = self.cards.keyboard_pages.create(dynamic_buttons(25), Event(),
                                               card_content=content, image_tokens=("owned-help-image",))
        checks = []
        image_available = [True]

        def has_tokens(tokens):
            checks.append(tokens)
            return image_available[0]

        self.cards.publisher.has_tokens = has_tokens
        plugin, handler = types.SimpleNamespace(transport=self.cards), page_handler()
        for number in (2, 1):
            event = Event()
            results = [result async for result in handler(plugin, event, page.token, number)]
            text = results[0].chain[0].text
            self.assertEqual(text, f"{content}\n\n按钮第 {number}/4 页")
            self.assertEqual(text.count(image_url), 1)
            self.assertNotIn("操作菜单", text)
            self.assertNotIn("#切换账号", text)
            self.assertEqual(event.extras[pages.PAGE_HINT_KEY], (page.token, number))
        self.assertEqual(checks, [("owned-help-image",)] * 2)

        wrong_owner = Event(sender="bob")
        rejected = [result async for result in handler(plugin, wrong_owner, page.token, 2)]
        self.assertNotIn(image_url, rejected[0].chain[0].text)
        self.assertNotIn("原始说明", rejected[0].chain[0].text)
        self.assertEqual(len(checks), 2)

        image_available[0] = False
        missing_image_event = Event()
        rejected = [result async for result in handler(plugin, missing_image_event, page.token, 2)]
        self.assertIn("菜单已过期", rejected[0].chain[0].text)
        self.assertNotIn(image_url, rejected[0].chain[0].text)
        self.assertNotIn(pages.PAGE_HINT_KEY, missing_image_event.extras)

        image_available[0] = True
        now[0] = 11.0
        expired_event = Event()
        rejected = [result async for result in handler(plugin, expired_event, page.token, 1)]
        self.assertIn("菜单已过期", rejected[0].chain[0].text)
        self.assertNotIn(image_url, rejected[0].chain[0].text)
        self.assertNotIn(pages.PAGE_HINT_KEY, expired_event.extras)


if __name__ == "__main__":
    unittest.main()
