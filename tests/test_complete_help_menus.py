"""Full help navigation stays complete through menu selection and callbacks."""
import importlib
import unittest

import test_transport as fixtures
from test_keyboard_pages import Event, actions, pages


menus = fixtures.menus
transport = fixtures.transport
prompts = importlib.import_module("astrbot_plugin_official_cards.button_prompts")
resources = importlib.import_module("astrbot_plugin_official_cards.resource_menus")
sky = importlib.import_module("astrbot_plugin_official_cards.sky_menu")


class HelpEvent(Event):
    def __init__(self, command, *, admin=False, private=False):
        super().__init__(admin=admin, session="alice" if private else "group-openid")
        self.command = command
        if private:
            self.message_obj.raw_message = fixtures.C2CMessage()

    def get_message_str(self):
        return self.command


HELP_ALIASES = {
    "光遇": ("/光遇帮助", "#光遇菜单", "/光遇娱乐菜单", "/sky帮助", "/sky菜单", "/sky娱乐菜单"),
    "Pixiv": ("/pixiv帮助", "/pixiv_help", "/pixiv帮助 图片", "/pixiv_help text"),
    "JM": ("/jm帮助", "/jmhelp", "/jm", "/jmhelp0", "/jm帮助 文字"),
    "Pica": ("/pica帮助", "/picahelp", "/pica", "/pica帮助 文字"),
}


def expected_buttons(family, *, admin=False, private=False):
    return [item for item in menus.FAMILIES[family][2]
            if (admin or not item.get("admin_only"))
            and (private or not item.get("private_only"))
            and (not private or not item.get("group_only"))]


class CompleteHelpMenuTests(unittest.TestCase):
    def test_root_exposes_seventeen_distinct_categories_and_correct_destinations(self):
        _, buttons = menus.menu_page(is_admin=False)
        self.assertEqual(len(buttons), 17)
        self.assertEqual({item["label"] for item in buttons}, set(menus.FAMILIES))
        self.assertEqual(len({item["command"] for item in buttons}), 17)
        original_help = {"光遇": "/光遇帮助", "签到": "/签到帮助", "王者": "#王者帮助",
                         "音乐": "#R帮助", "Pixiv": "/pixiv帮助", "Pica": "/pica帮助", "JM": "/jm帮助"}
        for item in buttons:
            family = item["label"]
            self.assertEqual(item["command"], original_help.get(family, "/功能菜单 " + family))
            self.assertEqual(menus.infer_family(item["command"]), family)
        for alias, family in (("sky", "光遇"), ("pixiv", "Pixiv"), ("jm", "JM"), ("pica", "Pica")):
            text, selected = menus.menu_page(alias, is_admin=True, is_private=True)
            self.assertIn(menus.FAMILIES[family][0], text)
            self.assertEqual(selected[:-1], expected_buttons(family, admin=True, private=True))
            self.assertEqual(selected[-1]["command"], "/功能菜单")

    def test_all_help_aliases_select_the_full_matching_family(self):
        for family, aliases in HELP_ALIASES.items():
            for alias in aliases:
                with self.subTest(family=family, alias=alias):
                    event = HelpEvent(alias, admin=True, private=True)
                    buttons = menus.buttons_for_event(event, {})
                    self.assertEqual(buttons[:-1], expected_buttons(family, admin=True, private=True))
                    self.assertEqual(buttons[-1]["command"], "/功能菜单")
                    self.assertGreater(len(buttons), 5)

    def test_image_menu_hint_selects_full_family_for_natural_language_help(self):
        for family, hint in (("光遇", "sky"), ("Pixiv", "pixiv"), ("JM", "jm"), ("Pica", "pica")):
            event = HelpEvent("请把功能菜单发给我", admin=True, private=True)
            actual = menus.buttons_for_event(event, {"family": hint, "menu": True})
            self.assertEqual(actual[:-1], expected_buttons(family, admin=True, private=True))
        sky = menus.buttons_for_event(HelpEvent("查看帮助", admin=True, private=True),
                                      {"family": "sky", "title": "光遇菜单"})
        self.assertEqual(sky[:-1], expected_buttons("光遇", admin=True, private=True))

    def test_ordinary_results_keep_compact_navigation_in_their_own_family(self):
        for family, command, hint in (("光遇", "/每日任务", "sky"),
                                      ("Pixiv", "/pixiv 风景", "pixiv"),
                                      ("JM", "/jm搜索 示例", "jm"),
                                      ("Pica", "/pica搜索 示例", "pica")):
            event = HelpEvent(command, admin=True, private=True)
            for metadata in ({}, {"family": hint}):
                with self.subTest(family=family, hint=metadata):
                    buttons = menus.buttons_for_event(event, metadata)
                    self.assertLessEqual(len(buttons), 5)
                    self.assertEqual(buttons[-1]["command"], "/功能菜单")
                    family_commands = {item["command"] for item in menus.FAMILIES[family][2]}
                    self.assertTrue(all(item["command"] in family_commands for item in buttons[:-1]))
                    self.assertTrue(buttons[:-1])

    def test_full_help_filters_admin_private_and_group_only_entries(self):
        observed_flags = set()
        for family in HELP_ALIASES:
            for item in menus.FAMILIES[family][2]:
                observed_flags.update(key for key in ("admin_only", "private_only", "group_only") if item.get(key))
            for admin, private in ((False, False), (False, True), (True, False), (True, True)):
                event = HelpEvent(HELP_ALIASES[family][0], admin=admin, private=private)
                actual = menus.buttons_for_event(event, {})
                self.assertEqual(actual[:-1], expected_buttons(family, admin=admin, private=private))
                _, selected = menus.menu_page(family, is_admin=admin, is_private=private)
                self.assertEqual(actual, selected)
        self.assertTrue({"admin_only", "private_only"}.issubset(observed_flags))
        group_pica = menus.buttons_for_event(HelpEvent("/pica帮助", admin=True), {})
        self.assertNotIn("/pica登录", {item["command"] for item in group_pica})
        public_jm = menus.buttons_for_event(HelpEvent("/jm帮助"), {})
        self.assertNotIn("/jm清理", {item["command"] for item in public_jm})

    def test_every_visible_action_survives_pagination_and_callback_conversion(self):
        for family in HELP_ALIASES:
            for private in (False, True):
                with self.subTest(family=family, private=private):
                    event = HelpEvent(HELP_ALIASES[family][0], admin=True, private=private)
                    original = menus.buttons_for_event(event, {})
                    expected = transport.normalize_buttons(original)
                    for original_item, normalized_item in zip(original, expected):
                        self.assertEqual(normalized_item["enter"], bool(original_item["enter"]),
                                         f"complete callback lost: {original_item['command']}")
                    cards = transport.CardTransport(fixtures.Publisher())
                    cards.callbacks_enabled = True
                    key = (event.get_platform_id(), type(event.message_obj.raw_message).__name__, "passive")
                    payload = cards._payload("帮助卡片", original, key, event=event)
                    payloads = [payload]
                    if cards.keyboard_pages.entries:
                        token = next(iter(cards.keyboard_pages.entries))
                        first = cards.keyboard_pages.get_page(token, 1, event)
                        for number in range(2, first.total + 1):
                            page = cards.keyboard_pages.get_page(token, number, event)
                            event.set_extra(pages.PAGE_HINT_KEY, (token, number))
                            payloads.append(cards._payload(page.text, page.buttons, key, event=event))
                    seen = []
                    for outgoing in payloads:
                        rows = outgoing["keyboard"]["content"]["rows"]
                        self.assertLessEqual(len(rows), 5)
                        self.assertTrue(all(len(row["buttons"]) <= 2 for row in rows))
                        for item in actions(outgoing["keyboard"]):
                            action = item["action"]
                            self.assertEqual(action["type"], 1)
                            command = cards.callback_actions.resolve(action["data"],
                                platform_id=event.get_platform_id(), scene="c2c" if private else "group",
                                session=event.get_session_id(), sender=event.get_sender_id())
                            self.assertIsNotNone(command)
                            if not command.startswith("/菜单翻页 "):
                                seen.append((item["render_data"]["label"], command))
                    self.assertEqual(len(seen), len(expected))
                    for (label, command), item in zip(seen, expected):
                        self.assertEqual(label, item["label"])
                        if item["enter"]:
                            self.assertEqual(command, item["command"])
                        else:
                            self.assertTrue(command.startswith("/按钮用法 "))
                            usage = cards.button_prompts.get(command.split()[1], event)
                            self.assertIsNotNone(usage)
                            detail = resources.resource_usage(item["command"]) or sky.sky_usage(item["command"])
                            self.assertIsNotNone(detail, item["command"])
                            self.assertIn(detail[0], usage)
                            self.assertIn("本次仅显示用法，未执行操作", usage)

    def test_resource_usage_is_used_by_the_shared_prompt_gateway(self):
        for _, _, buttons in resources.RESOURCE_FAMILIES.values():
            for item in buttons:
                if item["enter"]:
                    continue
                with self.subTest(command=item["command"]):
                    syntax, example, explanation = resources.resource_usage(item["command"])
                    text = prompts.usage_text(item["label"], item["command"])
                    self.assertIn(syntax, text)
                    self.assertIn(example, text)
                    self.assertIn(explanation, text)
                    self.assertNotIn("需要参数时请按该功能的帮助补全", text)


if __name__ == "__main__":
    unittest.main()
