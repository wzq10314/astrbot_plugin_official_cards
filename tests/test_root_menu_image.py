"""Root navigation sends a single image with the same complete keyboard."""
import ast
import asyncio
import tempfile
import types
import unittest
from pathlib import Path

import test_transport as fixtures
from test_complete_help_menus import HelpEvent


class ImageResult(fixtures.Chain):
    def use_t2i(self, value): return self
    def use_markdown(self, value):
        self.use_markdown_ = value
        return self


class MenuEvent(HelpEvent):
    def chain_result(self, parts): return ImageResult(parts)


def menu_handler(renderer, directory, queue=lambda *args: False):
    file = Path(__file__).resolve().parents[1] / 'main.py'
    tree = ast.parse(file.read_text(encoding='utf-8-sig'))
    plugin = next(item for item in tree.body if isinstance(item, ast.ClassDef))
    fn = next(item for item in plugin.body if isinstance(item, ast.AsyncFunctionDef) and item.name == 'show_menu')
    fn.decorator_list = []
    support = __import__('astrbot_plugin_official_cards.support', fromlist=['set_card_hint'])
    routes = __import__('astrbot_plugin_official_cards.menu_routes', fromlist=['original_help_command'])
    values = {'AstrMessageEvent': MenuEvent, 'asyncio': asyncio,
              'menu_page': fixtures.menus.menu_page, 'FAMILIES': fixtures.menus.FAMILIES,
              'FAMILY_ALIASES': fixtures.menus.FAMILY_ALIASES,
              'event_is_private': fixtures.menus.event_is_private,
              'is_qq_official': support.is_qq_official, 'set_card_hint': support.set_card_hint,
              'Image': types.SimpleNamespace(fromFileSystem=fixtures.Image),
              'StarTools': types.SimpleNamespace(get_data_dir=lambda name: directory),
              'render_menu_image': renderer, 'logger': types.SimpleNamespace(info=lambda *args: None)}
    values.update(original_help_command=routes.original_help_command, queue_original_help=queue)
    exec(compile(ast.fix_missing_locations(ast.Module(body=[fn], type_ignores=[])), str(file), 'exec'), values)
    return values[fn.name]


class RootMenuImageTests(unittest.IsolatedAsyncioTestCase):
    async def test_existing_artwork_routes_once_without_rendering_or_intermediate_reply(self):
        for category in ('光遇', '签到', '王者', '音乐', 'Pixiv', 'Pica', 'JM'):
            with self.subTest(category=category), tempfile.TemporaryDirectory() as directory:
                queued = []
                def renderer(*args, **kwargs):
                    self.fail('Existing help artwork must not render a category image')
                def queue(context, event, selected):
                    queued.append(selected)
                    return True
                event = MenuEvent('/功能菜单 ' + category)
                event.stop_event = lambda: setattr(event, 'stopped', True)
                handler = menu_handler(renderer, Path(directory), queue)
                result = [item async for item in handler(types.SimpleNamespace(context=None), event, category)]
                self.assertEqual(result, [])
                self.assertEqual(queued, [category])
                self.assertTrue(event.stopped)

    async def test_root_image_has_all_categories_and_keeps_paged_buttons(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            calls = []
            def renderer(categories, *, cache_dir):
                calls.append((categories, cache_dir))
                return root / 'menu.webp'
            event = MenuEvent('/功能菜单')
            results = [item async for item in menu_handler(renderer, root)(None, event)]
            self.assertEqual(len(results), 1)
            result = results[0]
            self.assertEqual(len(result.chain), 1)
            self.assertIsInstance(result.chain[0], fixtures.Image)
            self.assertEqual(len(calls[0][0]), 17)
            # The installed 1.0.12 already supports official group management.
            self.assertEqual({row[0] for row in calls[0][0] if not row[3]}, {'贴表情'})
            self.assertEqual(len(event.extras['qq_official_card']['buttons']), 17)
            cards = fixtures.transport.CardTransport(fixtures.Publisher())
            event.send_buffer = result
            await cards.send_event(event, result)
            payload = event.bot.api.calls[0]
            self.assertIn('![图片', payload['markdown']['content'])
            self.assertNotIn('点击分类查看命令', payload['markdown']['content'])
            self.assertIn('按钮第 1/3 页', payload['markdown']['content'])
            self.assertIn('keyboard', payload)

    async def test_root_failure_falls_back_and_category_is_sent_to_card_renderer(self):
        with tempfile.TemporaryDirectory() as directory:
            calls = []
            def unavailable(*args, **kwargs):
                calls.append(1)
                raise RuntimeError('no CJK font')
            handler = menu_handler(unavailable, Path(directory))
            event = MenuEvent('/功能菜单')
            results = [item async for item in handler(None, event)]
            self.assertIn('功能菜单', results[0].chain[0].text)
            self.assertEqual(len(event.extras['qq_official_card']['buttons']), 17)
            selected = MenuEvent('/功能菜单 Pixiv')
            result = [item async for item in handler(types.SimpleNamespace(context=None), selected, 'Pixiv')]
            self.assertIn('/pixiv帮助', result[0].chain[0].text)
            self.assertNotIn('完整菜单', result[0].chain[0].text)
            self.assertEqual(len(calls), 1)


if __name__ == '__main__': unittest.main()
