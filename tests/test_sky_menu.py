"""Sky navigation is checked against the installed plugin's actual command matcher."""
import ast
import importlib.util
from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('sky_menu_fixture', ROOT / 'sky_menu.py')
sky = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sky)
tree = ast.parse((ROOT.parent / 'astrbot_plugin_sky/main.py').read_text(encoding='utf-8'))
pattern = next(ast.literal_eval(node.value) for node in tree.body
               if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name)
                  and target.id == 'PATTERN' for target in node.targets))


class SkyMenuTests(unittest.TestCase):
    def test_all_complete_buttons_are_real_simplified_commands(self):
        for button in sky.SKY_FAMILY[2]:
            if button['enter']:
                with self.subTest(command=button['command']):
                    self.assertIsNotNone(re.fullmatch(pattern, button['command']))
                    self.assertNotRegex(button['command'], r'[<>\[\]]|YYYY|XX')
        commands = {row['command'] for row in sky.SKY_FAMILY[2]}
        self.assertIn('/每日任务', commands)
        self.assertNotIn('/光遇 每日任务', commands)
        self.assertNotIn('/光遇', commands)

    def test_every_parameter_button_has_inert_specific_usage(self):
        for button in sky.SKY_FAMILY[2]:
            if not button['enter']:
                with self.subTest(command=button['command']):
                    usage = sky.sky_usage(button['command'])
                    self.assertIsNotNone(usage)
                    self.assertEqual(len(usage), 3)
                    self.assertTrue(all(usage))

    def test_parameter_examples_match_actual_routes_after_completion(self):
        examples = {
            '/YYYY年M月碎石': '/2026年9月碎石',
            '/XX季多久未复刻': '/追光季多久未复刻',
            '/YYYY年复刻记录': '/2026年复刻记录',
            '/YYYY年复刻日历': '/2026年复刻日历',
            '/光遇绑定': '/光遇绑定 123456', '/光遇切换': '/光遇切换 1',
            '/光遇删除': '/光遇删除 1', '/光遇绑定好友码': '/光遇绑定好友码 ABCD-EFGH-IJKL',
            '/光遇绑定长ID': '/光遇绑定长ID example-long-id',
            '/存入盲盒': '/存入盲盒ABCD-EFGH-IJKL*国服',
            '/绑定token': '/绑定token fixture-token', '/解绑token': '/解绑token',
            '/国服id绑定': '/国服id绑定 ABCD-EFGH-IJKL',
            '/国服id切换': '/国服id切换 1', '/国服id删除': '/国服id删除 1',
        }
        inputs = {row['command'] for row in sky.SKY_FAMILY[2] if not row['enter']}
        self.assertEqual(inputs, set(examples))
        for command in examples.values():
            self.assertIsNotNone(re.fullmatch(pattern, command), command)

    def test_group_menu_hides_private_credentials_and_blindbox_storage(self):
        for admin in (False, True):
            commands = {row['command'] for row in sky.sky_buttons(is_admin=admin, is_private=False)}
            for command in ('/绑定token', '/解绑token', '/存入盲盒'):
                self.assertNotIn(command, commands)
            self.assertIn('/token绑定状态', commands)
            self.assertIn('/蜡烛变化查询', commands)

    def test_group_reminders_require_admin_and_group_context(self):
        controls = [row for row in sky.SKY_FAMILY[2] if row.get('group_only')]
        self.assertEqual(len(controls), 9)
        self.assertTrue(all(row.get('admin_only') for row in controls))
        control_commands = {row['command'] for row in controls}
        for admin, private in ((False, False), (False, True), (True, True)):
            visible = {row['command'] for row in sky.sky_buttons(is_admin=admin, is_private=private)}
            self.assertFalse(visible & control_commands)
        visible = {row['command'] for row in sky.sky_buttons(is_admin=True, is_private=False)}
        self.assertTrue(control_commands <= visible)

    def test_owner_diagnostics_are_not_public(self):
        for private in (False, True):
            public = {row['command'] for row in sky.sky_buttons(is_admin=False, is_private=private)}
            owner = {row['command'] for row in sky.sky_buttons(is_admin=True, is_private=private)}
            for command in ('/光遇接口状态', '/光遇更新'):
                self.assertNotIn(command, public)
                self.assertIn(command, owner)

    def test_account_mutations_never_run_with_missing_parameters(self):
        prefixes = ('/光遇绑定', '/光遇切换', '/光遇删除', '/国服id绑定',
                    '/国服id切换', '/国服id删除', '/绑定token', '/解绑token', '/存入盲盒')
        for button in sky.SKY_FAMILY[2]:
            if button['command'].startswith(prefixes):
                self.assertFalse(button['enter'], button['command'])

    def test_catalog_is_unique_and_filtered_returns_copies(self):
        commands = [row['command'] for row in sky.SKY_FAMILY[2]]
        self.assertEqual(len(commands), len(set(commands)))
        self.assertGreaterEqual(len(commands), 65)
        visible = sky.sky_buttons(is_admin=True, is_private=False)
        visible[0]['label'] = 'fixture mutation'
        self.assertEqual(sky.SKY_FAMILY[2][0]['label'], '光遇帮助')

    def test_help_aliases_do_not_expand_ordinary_results(self):
        for family in ('光遇', 'sky', 'SKY'):
            for suffix in ('帮助', '菜单', '娱乐菜单'):
                for prefix in ('', '/', '#'):
                    self.assertTrue(sky.sky_help_family(prefix + family + suffix))
        for command in (None, '', '/光遇', '/每日任务', '/光遇状态', '/光遇帮助 extra',
                        '/光遇帮助\n/解绑token'):
            self.assertFalse(sky.sky_help_family(command))

    def test_usage_does_not_echo_supplied_credentials_or_unknown_commands(self):
        usage = sky.sky_usage('/绑定token fixture-private-value')
        self.assertIsNotNone(usage)
        self.assertNotIn('fixture-private-value', str(usage))
        self.assertEqual(sky.sky_usage('#国服id切换'), sky.sky_usage('/国服id切换'))
        self.assertIsNone(sky.sky_usage('/未知命令'))
        self.assertIsNone(sky.sky_usage('/绑定token\nfixture-private-value'))


if __name__ == '__main__':
    unittest.main()
