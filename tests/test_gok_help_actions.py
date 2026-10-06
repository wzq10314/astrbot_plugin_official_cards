"""Check the real GloryOfKings help keyboard against the official transport policy."""
import ast
import importlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

import test_transport as fixtures


ROOT = Path(__file__).resolve().parents[1]
GOK = ROOT.parent / 'astrbot_plugin_gloryofkings'
actions = importlib.import_module('astrbot_plugin_official_cards.button_actions')


class GokHelpActions(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        node = os.environ.get('GOK_NODE') or shutil.which('node')
        if not node:
            raise unittest.SkipTest('Node.js is needed to inspect the actual help keyboard')
        script = r"""
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import {pathToFileURL} from 'node:url';
const root=process.argv[1];
const {helpButtonRows}=await import(pathToFileURL(path.join(root,'engine/help-buttons.mjs')));
const source=fs.readFileSync(path.join(root,'engine/upstream/apps/help.js'),'utf8')
  .replace(/^import .*$/gm,'').replace('export class Help','class Help')
  +'\nglobalThis.sections=[...helpSections,...Object.values(subHelpSections)];';
const context=vm.createContext({plugin:class {}});
vm.runInContext(source,context);
const owner={isMaster:true,isGroup:false,msg:'#王者帮助'};
const all=helpButtonRows(owner,context.sections).flat();
const callbacks=[...new Set(all.filter(b=>b.callback).map(b=>b.callback))];
const publicPrivate=helpButtonRows({...owner,isMaster:false},context.sections).flat();
const ownerGroup=helpButtonRows({...owner,isGroup:true},context.sections).flat();
console.log(JSON.stringify({all,callbacks,publicPrivate,ownerGroup}));
"""
        result = subprocess.run([node, '--input-type=module', '-e', script, str(GOK)],
                                capture_output=True, text=True, encoding='utf-8', timeout=30)
        if result.returncode:
            raise AssertionError(result.stdout + result.stderr)
        cls.generated = json.loads(result.stdout)

    def test_every_generated_complete_command_submits(self):
        self.assertGreater(len(self.generated['callbacks']), 150)
        for command in self.generated['callbacks']:
            with self.subTest(command=command):
                self.assertTrue(actions.is_complete_callback(command))
                button = fixtures.transport.normalize_buttons([{'text': '帮助', 'callback': command}])[0]
                self.assertTrue(button['enter'])
                self.assertEqual(button['command'], command)

    def test_exact_allowlist_tracks_actual_keyboard_without_placeholders(self):
        self.assertEqual(actions._GOK_HELP_CALLBACKS, frozenset(self.generated['callbacks']))
        for command in actions._GOK_HELP_CALLBACKS:
            with self.subTest(command=command):
                self.assertNotRegex(command, r'[\[\]<>@\\^$|{}()]|查询N战绩')
                self.assertTrue(command.startswith('#'))

    def test_required_parameters_remain_editable(self):
        inputs = [button for button in self.generated['all'] if button.get('input')]
        self.assertGreater(len(inputs), 15)
        for button in inputs:
            with self.subTest(command=button['input']):
                self.assertFalse(actions.is_complete_callback(button['input']))
                normalized = fixtures.transport.normalize_buttons([button])[0]
                self.assertFalse(normalized['enter'])
                self.assertEqual(normalized['command'], button['input'])

    def test_original_input_intent_wins_for_complete_actions(self):
        for command in ['#王者帮助', '#营地消息开', '#关闭周报推送', '#营地观战 在播']:
            button = fixtures.transport.normalize_buttons([
                {'text': '编辑', 'input': command, 'callback': command, 'enter': True}])[0]
            self.assertFalse(button['enter'])

    def test_unknown_parameters_and_injections_are_not_auto_submitted(self):
        for command in ['#营地观战 停 [编号]', '#查询[账号序号]战绩', '#查询N战绩',
                        '#王者更新 未审核参数', '#王者数据备份 token', '#营地消息开 其他人',
                        '#营地共享库令牌 token', '#删除营地 1', '#切换营地 1',
                        '#营地观战 在播\n#王者数据备份', '#关闭周报推送\x00']:
            with self.subTest(command=command):
                self.assertFalse(actions.is_complete_callback(command))

    def test_owner_controls_are_absent_from_group_and_ordinary_private_help(self):
        for key in ('publicPrivate', 'ownerGroup'):
            values = [button.get('callback') or button.get('input') for button in self.generated[key]]
            for command in ['#王者设置', '#王者数据备份', '#营地消息部署',
                            '#营地共享库令牌 <令牌>', '#营地观战接入 <地址> <令牌>']:
                with self.subTest(context=key, command=command):
                    self.assertNotIn(command, values)

    def test_existing_parameterized_query_patterns_are_preserved(self):
        for command in ['#王者主页2', '#查询361897277巅峰战绩3', '#巅峰总排名刷新',
                        '#排位表现361897277s43', '#查皮肤元流之子(法师)', '#英雄梯度游走']:
            self.assertTrue(actions.is_complete_callback(command), command)


class GokRuntimeHook(unittest.TestCase):
    def test_hook_is_official_only_and_preserves_shared_auth(self):
        tree = ast.parse((GOK / 'services/bridge.py').read_text(encoding='utf-8'))
        calls = []
        for node in ast.walk(tree):
            if isinstance(node, ast.If) and ast.unparse(node.test) == 'self.official':
                calls.extend(child.func.id for statement in node.body for child in ast.walk(statement)
                             if isinstance(child, ast.Call) and isinstance(child.func, ast.Name))
        self.assertEqual(calls.count('adapt_help_buttons'), 1)
        self.assertEqual(calls.count('adapt_shared_query_auth'), 1)
        all_hooks = [node for node in ast.walk(tree) if isinstance(node, ast.Call)
                     and isinstance(node.func, ast.Name) and node.func.id == 'adapt_help_buttons']
        self.assertEqual(len(all_hooks), 1)

    def test_runtime_patch_keeps_image_and_vendor_intact_and_fails_closed(self):
        spec = importlib.util.spec_from_file_location('gok_help_patch_fixture', GOK / 'services/help_buttons.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        engine = GOK / 'engine'
        vendor = engine / 'upstream/apps/help.js'
        original = vendor.read_bytes()
        with tempfile.TemporaryDirectory(prefix='gok-help-hook-') as folder:
            runtime = Path(folder)
            target = runtime / 'plugins/GloryOfKings-Plugin/apps/help.js'
            target.parent.mkdir(parents=True)
            target.write_bytes(original)
            self.assertTrue(module.adapt_help_buttons(engine, runtime))
            adapted = target.read_text(encoding='utf-8')
            self.assertIn('inventoryImage, buildHelpButtons(e, sections', adapted)
            self.assertEqual(adapted.count('import {buildHelpButtons}'), 1)
            self.assertEqual(vendor.read_bytes(), original)
            with self.assertRaisesRegex(ValueError, 'help button hook changed'):
                module.adapt_help_buttons(engine, runtime)


if __name__ == '__main__':
    unittest.main()
