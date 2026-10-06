"""Classify real plugin help bodies without importing plugins or using services."""
import ast
import asyncio
import importlib
import json
from pathlib import Path
import shutil
import subprocess
from types import SimpleNamespace
import unittest

import test_transport as fixtures


help_images = importlib.import_module('astrbot_plugin_official_cards.help_images')
PLUGINS = Path(__file__).resolve().parents[2]


def tree(relative):
    return ast.parse((PLUGINS / relative).read_text(encoding='utf-8-sig'))


def constant(relative, name):
    for node in tree(relative).body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == name for t in node.targets):
            return ast.literal_eval(node.value)
    raise AssertionError(f'Missing source constant: {relative}:{name}')


def returned_literal(relative, function):
    node = next(n for n in ast.walk(tree(relative))
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == function)
    return ast.literal_eval(next(n.value for n in ast.walk(node) if isinstance(n, ast.Return)))


def event(command, admin=False):
    return SimpleNamespace(get_message_str=lambda: command, is_admin=lambda: admin)


def title(command, body, **kwargs):
    return help_images.text_help_title(event(command, kwargs.pop('admin', False)), kwargs, body)


class RealHelpBodyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sky = constant('astrbot_plugin_sky/main.py', 'HELP')
        cls.token = constant('astrbot_plugin_sky/currency.py', 'HELP')
        cls.extra = constant('astrbot_plugin_qq_like/extras.py', 'EXTRA_HELP')
        cls.like = constant('astrbot_plugin_qq_like/main.py', 'HELP')
        cls.steam = constant('steam_status_monitor_V3/src/presentation/commands/ops.py', 'HELP_TEXT')
        cls.music = returned_literal('astrbot_plugin_rconsole/modules/help.py', 'render')
        cls.pica = returned_literal('astrbot_plugin_qq_like/pica/core/formatter.py', 'help_text')
        cls.jm = returned_literal('astrbot_plugin_qq_like/jm/core/formatter.py', 'help_text')
        cls.gift = next(n.value for n in ast.walk(tree('astrbot_plugin_sky/main.py'))
                        if isinstance(n, ast.Constant) and isinstance(n.value, str)
                        and n.value.startswith('国服id绑定 好友码'))

    def test_dailyhub_actual_handler_without_help_keyword(self):
        method = next(n for n in ast.walk(tree('astrbot_plugin_dailyhub/main.py'))
                      if isinstance(n, ast.AsyncFunctionDef) and n.name == 'cmd_menu')
        method.decorator_list = []
        namespace = {'AstrMessageEvent': object,
                     'sources': SimpleNamespace(SOURCES=[SimpleNamespace(
                         key='news', emoji='📰', name='新闻', aliases=['新闻'])])}
        exec(compile(ast.Module(body=[method], type_ignores=[]), '<actual dailyhub cmd_menu>', 'exec'), namespace)
        plugin = SimpleNamespace(subs=SimpleNamespace(list_for_umo=lambda _: []), _src_cfg=lambda _: {})
        request = SimpleNamespace(unified_msg_origin='test-session', plain_result=lambda text: text)

        async def invoke():
            return [item async for item in namespace['cmd_menu'](plugin, request)]

        body, = asyncio.run(invoke())
        self.assertNotIn('帮助', body)
        self.assertNotIn('菜单', body)
        for command in ('/资讯菜单', '/资讯帮助', '/dailyhub'):
            self.assertEqual(title(command, body), '资讯菜单')

    def test_short_extension_and_like_help_use_actual_fingerprints(self):
        self.assertNotIn('帮助', self.extra)
        self.assertEqual(title('/扩展帮助', self.extra), '扩展帮助')
        self.assertEqual(title('#点赞帮助', self.like), '点赞帮助')
        self.assertIsNone(title('/状态', self.extra))

    def test_actual_steam_and_music_help(self):
        self.assertEqual(title('/steam help', self.steam), 'Steam 帮助')
        for command in ('#rhelp', '#RHELP', '#rhelp 说明', '#R帮助', '#R插件菜单',
                        '#r命令', '#R说明', '#R功能', '#R指令', '#R使用说明'):
            self.assertEqual(title(command, self.music), '音乐与解析帮助', command)
        for command in ('#rhelpful', '#rstatus', '/steam list', '/steam helpme'):
            self.assertIsNone(title(command, self.music if command.startswith('#') else self.steam))

    def test_sky_main_help_and_text_report_prefix(self):
        for command in ('/光遇帮助', '#光遇菜单', '光遇娱乐菜单', '/sky帮助', '#SKY菜单', '/sky娱乐菜单'):
            for body in (self.sky, '光遇菜单\n' + self.sky):
                self.assertIsNotNone(title(command, body), command)
        self.assertIsNone(title('/光遇状态', self.sky))
        self.assertIsNone(title('/光遇', self.sky))

    def test_actual_gift_help_has_no_help_keyword(self):
        self.assertNotIn('帮助', self.gift)
        self.assertEqual(title('/礼包查询帮助', self.gift), '礼包查询帮助')

    def test_token_help_and_only_no_argument_binding_prompts(self):
        for command in ('/光遇token帮助', '#绑定token', '这是我的token', '/我的TOKEN'):
            self.assertEqual(title(command, self.token), '光遇 Token 绑定帮助')
        for command in ('/绑定token placeholder', '/绑定token：https://example.test/?token=placeholder',
                        '/这是我的token:placeholder', '/我的token placeholder', '/解绑token',
                        '/光遇token帮助 placeholder', '/绑定token\nplaceholder',
                        '/我的token\r\nplaceholder'):
            self.assertIsNone(title(command, self.token), command)

    def test_actual_resource_formatters_and_supported_help_arguments(self):
        for command in ('/pica', '/pica帮助', '/picahelp', '/pica帮助 文字', '/picahelp image'):
            self.assertEqual(title(command, self.pica), 'Pica 帮助')
        for command in ('/jm', '/jmhelp0', '/jm帮助', '/jmhelp', '/jm帮助 文字', '/jmhelp image'):
            self.assertEqual(title(command, self.jm), 'JM 帮助')
        self.assertIsNone(title('/pica 风景', self.pica))
        self.assertIsNone(title('/jm 123', self.jm))
        self.assertIsNone(title('/pica搜索 帮助', self.pica))
        self.assertIsNone(title('/jm搜索 帮助', self.jm))

    def test_same_real_bodies_cannot_be_reclassified_by_family_hints(self):
        for command, body in (('/今日小猪', self.sky), ('/心动小镇', self.sky),
                              ('/learning_status', self.steam), ('/meme help', self.music),
                              ('/光遇绑定 123', self.sky), ('/pica搜索 菜单', self.pica),
                              ('/jm详情 123', self.jm)):
            self.assertIsNone(title(command, body, menu=True, family='sky', title='光遇菜单'))

    def test_help_invocations_keep_real_unavailable_messages_as_text(self):
        errors = (
            '签到帮助图片缺失，请联系管理员重新安装插件',
            '插件服务未就绪，请检查启动日志',
            '未启用：哔咔功能已关闭（需管理员在后台配置 pica_enabled）',
            '帮助消息加载失败，请检查配置文件。', 'help.text',
            '此命令仅允许 AstrBot 管理员或插件配置中的管理员使用。',
            '当前平台不支持给消息贴表情。该功能需要 NapCat / OneBot，QQ 官方机器人暂不提供此接口。',
        )
        for command in ('/签到帮助', '/lmem help', '/pica帮助', '/pixiv帮助',
                        '#rhelp', '/资讯菜单', '/光遇帮助', '/扩展帮助'):
            for body in errors:
                self.assertIsNone(title(command, body), (command, body))

    def test_lmem_command_list_structure_and_denial_precedence(self):
        # Locale JSON is absent in this source snapshot; match stable command entries.
        body = 'LivingMemory Help\n/lmem status - status\n/lmem search <text> - search'
        self.assertEqual(title('/lmem help', body, admin=True), '长期记忆帮助')
        for prefix in ('权限不足', '❌ 插件服务未就绪', 'Permission denied', 'Error: backend unavailable'):
            self.assertIsNone(title('/lmem help', prefix + '\n' + body, admin=True))
        self.assertIsNone(title('/lmem search help', body, admin=True))
        self.assertIsNone(title('/lmem help', '仅管理员可用\n/lmem status - status\n重复 /lmem status'))

    def test_pixiv_external_help_requires_heading_and_distinct_commands(self):
        body = 'Pixiv 帮助\n- `/pixiv搜索 <词>` 搜索\n- `/pixiv详情 <ID>` 详情'
        for command in ('/pixiv帮助', '/pixiv_help', '/pixiv帮助 文字', '/pixiv_help 完整'):
            self.assertEqual(title(command, body), 'Pixiv 帮助')
        self.assertIsNone(title('/pixiv搜索 help', body))
        self.assertIsNone(title('/pixiv帮助', '搜索结果\n' + body))
        self.assertIsNone(title('/pixiv帮助', 'Pixiv 帮助\n/pixiv搜索 菜单\n/pixiv搜索 帮助'))

    def test_real_external_help_delegates_and_permissions_are_still_upstream(self):
        memory = tree('astrbot_plugin_livingmemory/main.py')
        function = next(n for n in ast.walk(memory) if isinstance(n, ast.AsyncFunctionDef) and n.name == 'help')
        self.assertTrue(any('PermissionType.ADMIN' in ast.unparse(d) for d in function.decorator_list))
        handler = tree('astrbot_plugin_livingmemory/core/command_handler.py')
        self.assertTrue(any(isinstance(n, ast.Call) and ast.unparse(n) == "t('help.text')" for n in ast.walk(handler)))
        pixiv = tree('astrbot_plugin_qq_like/pixiv_reborn/plugin.py')
        function = next(n for n in ast.walk(pixiv) if isinstance(n, ast.AsyncFunctionDef) and n.name == 'pixiv_help')
        self.assertIn("get_help_message('pixiv_help'", ast.unparse(function))

    def test_actual_gok_fallback_main_subhelp_aliases_and_keyword_filter(self):
        node = shutil.which('node')
        if not node:
            candidate = Path('C:/Program Files/nodejs/node.exe')
            node = str(candidate) if candidate.is_file() else None
        if not node:
            self.skipTest('Node unavailable; actual upstream JS fallback cannot execute')
        path = PLUGINS / 'astrbot_plugin_gloryofkings/engine/upstream/apps/help.js'
        script = """const fs=require('fs'),vm=require('vm');
const source=fs.readFileSync(process.argv[1],'utf8').replace(/^import .*$/gm,'').replace(/^export /gm,'');
const result=vm.runInNewContext(source+'\\nJSON.stringify([renderTextHelp(helpSections),renderTextHelp([helpSections[0]],"账号")])',{plugin:class{}});
process.stdout.write(result);"""
        result = subprocess.run([node, '-e', script, str(path)], check=True, capture_output=True, text=True, encoding='utf-8')
        main, keyword = json.loads(result.stdout)
        for command in ('#王者帮助', '王者荣耀插件帮助', '#王者农药pluginhelp', '#王者帮助 账号',
                        '#查询战绩帮助', '#英雄帮助', '#英雄相关帮助', '#皮肤帮助',
                        '#营地共享帮助', '#营地ID共享帮助', '#观战帮助', '#营地观战帮助',
                        '#营地消息帮助', '#战绩推送帮助', '#群战绩报告帮助'):
            self.assertIsNotNone(title(command, keyword if '账号' in command else main), command)
        self.assertIsNone(title('#王者主页', main))
        self.assertIsNone(title('#营地观战 1', main))
        self.assertIsNone(title('#王者帮助 不存在', '没有找到和「不存在」相关的指令，发送 #王者帮助 看全部功能'))


if __name__ == '__main__':
    unittest.main()
