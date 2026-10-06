"""Resource navigation covers registered commands without invoking a service."""
import ast
import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("resource_menus_isolated", ROOT / "resource_menus.py")
menus = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(menus)


def registered_commands():
    source = ROOT.parent / "astrbot_plugin_qq_like" / "main.py"
    tree = ast.parse(source.read_text(encoding="utf-8-sig"))
    result = {}
    for function in ast.walk(tree):
        if not isinstance(function, ast.AsyncFunctionDef):
            continue
        for decorator in function.decorator_list:
            if (isinstance(decorator, ast.Call) and isinstance(decorator.func, ast.Attribute)
                    and decorator.func.attr == "command" and decorator.args
                    and isinstance(decorator.args[0], ast.Constant)):
                name = decorator.args[0].value.casefold()
                aliases = set()
                for keyword in decorator.keywords:
                    if keyword.arg == "alias":
                        aliases.update(alias.casefold() for alias in ast.literal_eval(keyword.value))
                result[name] = aliases
    return result


class ResourceMenuTests(unittest.TestCase):
    def test_every_registered_resource_function_has_one_canonical_button(self):
        registered = registered_commands()
        for family, (_, _, buttons) in menus.RESOURCE_FAMILIES.items():
            with self.subTest(family=family):
                commands = [item["command"].split()[0].lstrip("/").casefold() for item in buttons]
                expected = {name for name in registered if name.startswith(family.casefold())}
                # These standalone entry points already resolve to each family's help.
                if family in {"JM", "Pica"}:
                    expected.remove(family.casefold())
                self.assertEqual(set(commands), expected)
                self.assertEqual(len(commands), len(set(commands)))
                self.assertTrue(all(len(button["label"]) <= 40 for button in buttons))
        self.assertEqual({family: len(value[2]) for family, value in menus.RESOURCE_FAMILIES.items()},
                         {"Pixiv": 45, "JM": 8, "Pica": 15})

    def test_helpers_always_have_inert_syntax_example_and_explanation(self):
        for _, _, buttons in menus.RESOURCE_FAMILIES.values():
            for item in buttons:
                with self.subTest(command=item["command"]):
                    self.assertNotIn("<", item["command"])
                    self.assertNotIn("\n", item["command"])
                    if not item["enter"]:
                        usage = menus.resource_usage(item["command"])
                        self.assertIsInstance(usage, tuple)
                        self.assertEqual(len(usage), 3)
                        self.assertTrue(all(isinstance(value, str) and value for value in usage))
                        self.assertTrue(usage[0].startswith(item["command"]))
                    else:
                        self.assertNotIn("[", item["command"])
        self.assertIsNone(menus.resource_usage("/unrelated command"))
        self.assertIsNone(menus.resource_usage(None))

    def test_parameterless_login_logout_cleanup_and_stop_never_execute_from_menu(self):
        helpers = {item["command"]: item for value in menus.RESOURCE_FAMILIES.values() for item in value[2]}
        for command in ("/pica登录", "/pica退出", "/pica清理", "/jm清理", "/pixiv停止下载",
                        "/pixiv设置", "/pixivAI设置", "/pixiv删除标签", "/pixiv删除榜单"):
            self.assertFalse(helpers[command]["enter"], command)
        self.assertIn("不填账号密码会绑定后台默认账号", menus.resource_usage("/pica登录")[2])
        self.assertIn("清空全部", menus.resource_usage("/jm清理")[2])
        self.assertIn("清空全部", menus.resource_usage("/pica清理")[2])

    def test_default_invocations_supply_required_modes_and_valid_starting_pages(self):
        commands = {item["command"] for value in menus.RESOURCE_FAMILIES.values()
                    for item in value[2] if item["enter"]}
        for command in ("/pixiv最新 illust", "/pixiv排行 day", "/pixiv赞助推荐 5",
                        "/jm月排行 1", "/jm总排行 1", "/pica排行 H24", "/pica我的收藏 1"):
            self.assertIn(command, commands)
        self.assertFalse(any("r18" in command.casefold() for command in commands))

    def test_flags_filter_admin_and_private_entries_and_return_independent_buttons(self):
        for family, (_, _, original) in menus.RESOURCE_FAMILIES.items():
            public = menus.resource_buttons(family.casefold())
            self.assertTrue(all(not item.get("admin_only") and not item.get("private_only") for item in public))
            admin_group = menus.resource_buttons(family, is_admin=True)
            self.assertTrue(all(not item.get("private_only") for item in admin_group))
            full = menus.resource_buttons(family, is_admin=True, is_private=True)
            self.assertEqual(full, original)
            full[0]["label"] = "changed"
            self.assertNotEqual(original[0]["label"], "changed")
        login = "/pica登录"
        self.assertNotIn(login, {item["command"] for item in menus.resource_buttons("Pica", is_admin=True)})
        self.assertIn(login, {item["command"] for item in menus.resource_buttons("pica", is_private=True)})
        self.assertEqual(menus.resource_buttons("unknown"), [])

    def test_help_aliases_and_modes_are_recognized_without_capturing_resource_queries(self):
        registered = registered_commands()
        for family, canonical in (("Pixiv", "pixiv帮助"), ("JM", "jm帮助"), ("Pica", "pica帮助")):
            aliases = {canonical, *registered[canonical]}
            if family in {"JM", "Pica"}:
                aliases.update({family.casefold(), *registered[family.casefold()]})
            for alias in aliases:
                for suffix in ("", " 图片", " image", " 文字", " 完整", " text"):
                    self.assertEqual(menus.resource_help_family("/" + alias + suffix), family)
        for command in ("/pixiv", "/pixiv 风景", "/pixiv帮助 extra", "/pixiv帮助 text extra",
                        "/jm搜索 help", "/pica搜索 image", None):
            self.assertIsNone(menus.resource_help_family(command))


if __name__ == "__main__":
    unittest.main()
