import unittest
from types import SimpleNamespace
import test_transport as fixtures

transport=fixtures.transport


class CallbackTests(unittest.TestCase):
    def test_upstream_callback_submits_and_input_stays_editable(self):
        rows=[[{'text':'我的ID','callback':'#营地ID'},
               {'text':'查询战绩','callback':'#查询战绩'},
               {'text':'绑定营地','input':'#绑定营地'},
               {'text':'怎么获取ID','callback':'#绑定营地'},
               {'text':'查战力','input':'#查战力'}]]
        buttons=transport.normalize_buttons(rows)
        self.assertEqual([b['enter'] for b in buttons],[True,True,False,True,False])
        self.assertEqual(transport.normalize_buttons(buttons),buttons)
        keyboard=transport.build_keyboard(buttons)
        self.assertEqual([b['action']['enter'] for row in keyboard['content']['rows'] for b in row['buttons']],[True,True,False,True,False])

    def test_complete_query_variants_directly_submit(self):
        commands=['#王者主页2','#查询361897277巅峰战绩3','#排位战绩1','#常用英雄361897277',
                  '#皮肤墙','#缺皮肤','#巅峰总排名刷新','#排位表现361897277s43',
                  '#全部巅峰表现361897277 all','#巅峰趋势30 361897277',
                  '#英雄梯度游走','#查战力孙悟空','#查皮肤百里守约',
                  '#查皮肤元流之子(法师)','#英雄攻略元流之子（射手）']
        for command in commands:
            with self.subTest(command=command):
                button=transport.normalize_buttons([{'text':'查询','callback':command}])[0]
                self.assertTrue(button['enter'])

    def test_incomplete_mutating_and_injected_commands_do_not_submit(self):
        commands=['#查战力','#查皮肤','#删除营地1','#切换营地1','#开启战绩推送未知参数',
                  '#营地QQ全局登录未知参数','#王者主页\n#删除营地1','#查询战绩 1;退出',
                  '#王者主页\x00','#功能菜单 未知','/菜单翻页 forged 2',
                  '#查皮肤元流之子(法师）','#查战力英雄(任意命令)']
        for command in commands:
            with self.subTest(command=command):
                self.assertFalse(transport.normalize_buttons([{'text':'按钮','callback':command}])[0]['enter'])

    def test_explicit_edit_intent_wins_for_complete_commands(self):
        buttons=transport.normalize_buttons([
            {'text':'编辑','input':'#查询战绩','callback':'#王者主页','enter':True},
            {'text':'编辑','callback':'#查询战绩','enter':False},
        ])
        self.assertFalse(any(b['enter'] for b in buttons))
        self.assertEqual(buttons[0]['command'],'#查询战绩')

    def test_reviewed_complete_actions_keep_original_command_dispatch(self):
        commands = ['#营地wx全局登录', '#营地QQ全局登录', '#开启战绩推送', '#关闭战绩推送',
                    '#开启上下线提醒', '#开启皮肤上新推送', '#关闭皮肤上新推送',
                    '#开启王者公告推送', '#关闭王者公告推送']
        for command in commands:
            button = transport.normalize_buttons([{'text': '操作', 'callback': command}])[0]
            self.assertTrue(button['enter'])
            self.assertEqual(button['command'], command)


class CallbackTransportTests(unittest.IsolatedAsyncioTestCase):
    async def test_callback_survives_core_derived_message(self):
        cards=transport.CardTransport(fixtures.Publisher());cards.install()
        try:
            original=fixtures.Chain([fixtures.Plain('帮助')])
            original.qqofficial_buttons=[[{'text':'查询战绩','callback':'#查询战绩'}, {'text':'查战力','input':'#查战力'}]]
            event=fixtures.Event(original,fixtures.API())
            await event._post_send_one(original.derive(original.chain))
            row=event.bot.api.calls[0]['keyboard']['content']['rows'][0]['buttons']
            self.assertTrue(row[0]['action']['enter']);self.assertFalse(row[1]['action']['enter'])
        finally:cards.close()

    async def test_callback_remains_direct_after_menu_page(self):
        from test_keyboard_pages import Event,actions
        cards=transport.CardTransport(fixtures.Publisher())
        event=Event()
        buttons=transport.normalize_buttons([{'text':f'主页{i}','callback':f'#王者主页{i}'} for i in range(1,16)])
        page=cards.keyboard_pages.create(buttons,event)
        second=cards.keyboard_pages.get_page(page.token,2,event)
        keyboard=transport.build_keyboard(second.buttons,navigation_commands=second.navigation_commands)
        self.assertTrue(all(b['action']['enter'] for b in actions(keyboard)))
