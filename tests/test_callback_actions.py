import importlib
import types
import unittest

import test_transport as fixtures
from test_keyboard_pages import Event, actions

module = importlib.import_module('astrbot_plugin_official_cards.callback_actions')


class CallbackActionTests(unittest.TestCase):
    def test_bound_actions_reject_other_users_platforms_and_scenes(self):
        store = module.CallbackActionStore()
        action = store.create('#查询战绩', Event())
        self.assertEqual(action['type'], 1)
        self.assertEqual(action['permission'], {'type': 0, 'specify_user_ids': ['alice']})
        self.assertNotIn('enter', action)
        args = dict(platform_id='official-test', scene='group', session='group-openid', sender='alice')
        self.assertEqual(store.resolve(action['data'], **args), '#查询战绩')
        for field in args:
            changed = dict(args, **{field: 'elsewhere'})
            self.assertIsNone(store.resolve(action['data'], **changed))
        self.assertIsNone(store.resolve('#删除营地', **args))

    def test_private_keyboard_allows_tap_but_rejects_other_users_and_scenes(self):
        store = module.CallbackActionStore()
        for raw_name in ('C2CMessage', 'PatchedC2CMessage'):
            event = Event(session='alice', sender='alice')
            event.message_obj.raw_message = type(raw_name, (), {})()
            action = store.create('/功能菜单', event)
            self.assertEqual(action['permission'], {'type': 2})
            args = dict(platform_id='official-test', scene='c2c', session='alice', sender='alice')
            self.assertEqual(store.resolve(action['data'], **args), '/功能菜单')
            for field in args:
                self.assertIsNone(store.resolve(action['data'], **dict(args, **{field: 'other'})))

    def test_private_menu_prompts_and_pagination_use_private_permission(self):
        cards = fixtures.transport.CardTransport(fixtures.Publisher())
        cards.callbacks_enabled = True
        event = Event(session='alice', sender='alice')
        event.message_obj.raw_message = type('PatchedC2CMessage', (), {})()
        scope = dict(platform_id='official-test', scene='c2c', session='alice', sender='alice')
        for category in ['', *fixtures.menus.FAMILIES]:
            text, buttons = fixtures.menus.menu_page(category, is_admin=False)
            event.extras.clear()
            payload = cards._payload(text, buttons, ('official-test', 'PatchedC2CMessage', 'passive'), event=event)
            for button in actions(payload['keyboard']):
                action = button['action']
                self.assertEqual(action['type'], 1)
                self.assertEqual(action['permission'], {'type': 2})
                command = cards.callback_actions.resolve(action['data'], **scope)
                self.assertIsNotNone(command)
                self.assertIsNone(cards.callback_actions.resolve(action['data'], **dict(scope, sender='bob')))
                if command.startswith('/按钮用法 '):
                    self.assertIsNotNone(cards.button_prompts.get(command.split()[1], event))
                if command.startswith('/菜单翻页 '):
                    _, token, number = command.split()
                    selected = cards.keyboard_pages.get_page(token, int(number), event)
                    event.set_extra('qq_official_keyboard_page', (token, int(number)))
                    next_payload = cards._payload(selected.text, selected.buttons,
                        ('official-test', 'PatchedC2CMessage', 'passive'), event=event)
                    self.assertTrue(all(item['action']['permission'] == {'type': 2}
                                        for item in actions(next_payload['keyboard'])))

    def test_unbound_proactive_is_destination_bound_and_expires(self):
        now = [0]
        store = module.CallbackActionStore(ttl=10, max_entries=1, clock=lambda: now[0])
        self.assertIsNone(store.create('/功能菜单'))
        action = store.create('/功能菜单', scope=('official-test', 'group', 'group-openid'))
        args = dict(platform_id='official-test', scene='group', session='group-openid', sender='bob')
        self.assertEqual(store.resolve(action['data'], **args), '/功能菜单')
        newer = store.create('/状态', Event())
        self.assertIsNone(store.resolve(action['data'], **args))
        now[0] = 10
        self.assertIsNone(store.resolve(newer['data'], **dict(args, sender='alice')))
        self.assertFalse(store.entries)

    def test_all_menu_actions_are_type_one_and_helpers_only_reply_with_usage(self):
        cards = fixtures.transport.CardTransport(fixtures.Publisher())
        cards.callbacks_enabled = True
        event = Event()
        for category in ['', *fixtures.menus.FAMILIES]:
            text, buttons = fixtures.menus.menu_page(category, is_admin=False)
            payload = cards._payload(text, buttons, ('official-test', 'GroupMessage', 'passive'), event=event)
            for button in actions(payload['keyboard']):
                action = button['action']
                self.assertEqual(action['type'], 1)
                self.assertNotIn('enter', action)
                command = cards.callback_actions.resolve(action['data'], platform_id='official-test',
                    scene='group', session='group-openid', sender='alice')
                self.assertIsNotNone(command)
                if command.startswith('/按钮用法 '):
                    self.assertIsNotNone(cards.button_prompts.get(command.split()[1], event))

    def test_parameter_and_navigation_actions_survive_pagination(self):
        cards = fixtures.transport.CardTransport(fixtures.Publisher())
        cards.callbacks_enabled = True
        event = Event()
        buttons = [{'text': '切换', 'input': '#切换营地'}] * 15
        payload = cards._payload('菜单', buttons, ('official-test', 'GroupMessage', 'passive'), event=event)
        resolve = lambda action: cards.callback_actions.resolve(action['data'], platform_id='official-test',
            scene='group', session='group-openid', sender='alice')
        rendered = actions(payload['keyboard'])
        self.assertEqual([len(row['buttons']) for row in payload['keyboard']['content']['rows']], [2, 2, 2, 2, 1])
        for button in rendered[:-1]:
            command = resolve(button['action'])
            self.assertTrue(command.startswith('/按钮用法 '))
            self.assertIn('#切换营地', cards.button_prompts.get(command.split()[1], event))
        command = resolve(rendered[-1]['action'])
        self.assertTrue(command.startswith('/菜单翻页 '))
        _, token, page = command.split()
        event.set_extra('qq_official_keyboard_page', (token, int(page)))
        selected = cards.keyboard_pages.get_page(token, int(page), event)
        outgoing = cards._payload(selected.text, selected.buttons, ('official-test', 'GroupMessage', 'passive'), event=event)
        self.assertTrue(all(item['action']['type'] == 1 for item in actions(outgoing['keyboard'])))

    def test_interaction_reply_uses_event_id_not_synthetic_message_id(self):
        cards = fixtures.transport.CardTransport(fixtures.Publisher())
        event = Event()
        event.set_extra('qqofficial_interaction_event_id', 'real-interaction-id')
        payload = cards._payload('回复', [], ('official-test', 'GroupMessage', 'passive'),
                                 event=event, msg_id='not-a-real-message')
        self.assertNotIn('msg_id', payload)
        self.assertEqual(payload['event_id'], 'real-interaction-id')


class InteractionPlainReplyTests(unittest.IsolatedAsyncioTestCase):
    async def test_interaction_stream_uses_normal_event_reply_not_core_fake_message_id(self):
        cards = fixtures.transport.CardTransport(fixtures.Publisher())
        cards.install()
        try:
            event = Event(fixtures.Chain([fixtures.Plain('回复')]))
            event.set_extra('qqofficial_interaction_event_id', 'real-click')
            await event._post_send_one(event.send_buffer, stream={'state': 1})
            self.assertEqual(event.bot.api.calls[0]['event_id'], 'real-click')
            self.assertNotIn('msg_id', event.bot.api.calls[0])
        finally:
            cards.close()

    async def test_plain_fallback_keeps_click_event_reference(self):
        cards = fixtures.transport.CardTransport(fixtures.Publisher())
        api = fixtures.API()
        await cards._send_plain_session(types.SimpleNamespace(client=types.SimpleNamespace(api=api)),
            'group-openid', 'group', fixtures.Chain([fixtures.Plain('教程')]),
            'synthetic-id', event_id='real-interaction-id')
        self.assertEqual(api.calls[0]['event_id'], 'real-interaction-id')
        self.assertNotIn('msg_id', api.calls[0])
