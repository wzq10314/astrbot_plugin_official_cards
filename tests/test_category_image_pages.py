"""Per-page menu artwork must follow the same owned snapshot as its buttons."""
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from PIL import Image as PILImage

import test_transport as fixtures
from test_help_card_replay import TokenService
from test_keyboard_pages import Event, actions, page_handler, pages, support


transport = fixtures.transport


def category_buttons(count=19):
    return [{"label": f"功能{index + 1}", "command": f"#王者主页{10001 + index}", "enter": True}
            for index in range(count)]


def card_snapshots(count=3):
    return [[f"![第{number}页](https://example.test/api/file/page-{number})", [f"page-{number}"]]
            for number in range(1, count + 1)]


class CategorySnapshotTests(unittest.TestCase):
    def test_image_and_commands_use_the_same_page_and_inputs_are_copied(self):
        store, event, buttons = pages.KeyboardPageStore(), Event(), category_buttons()
        originals = category_buttons()
        cards = card_snapshots()
        expected_cards = [(content, tuple(tokens)) for content, tokens in cards]
        first = store.create(buttons, event, card_content="不得回放整份命令列表", page_cards=cards)
        self.assertIsNotNone(first)
        self.assertEqual(first.total, 3)
        cards[0][0] = "changed content"
        cards[0][1][0] = "changed token"
        cards.clear()
        buttons[0]["command"] = "/changed"
        buttons[0]["label"] = "changed"
        for number in (1, 2, 3, 1):
            selected = store.get_page(first.token, number, event)
            expected = originals[(number - 1) * pages.PAGE_SIZE:number * pages.PAGE_SIZE]
            actual = [button for button in selected.buttons
                      if button["command"] not in selected.navigation_commands]
            self.assertEqual(actual, expected)
            self.assertEqual((selected.card_content, selected.image_tokens), expected_cards[number - 1])
            self.assertEqual(selected.text, f"{expected_cards[number - 1][0]}\n\n按钮第 {number}/3 页")
            self.assertNotIn("不得回放", selected.text)
            self.assertNotIn("操作菜单", selected.text)

    def test_snapshot_retains_only_values_and_no_event_or_credentials(self):
        store, event = pages.KeyboardPageStore(), Event()
        event.set_extra("private_credentials", {"password": "do-not-copy-this-secret"})
        event.bot.client = object()
        first = store.create(category_buttons(), event, page_cards=card_snapshots())

        def assert_values(value):
            if isinstance(value, tuple):
                for item in value:
                    assert_values(item)
            else:
                self.assertIsInstance(value, (str, int, float, bool))

        assert_values(store.entries[first.token])
        self.assertNotIn("do-not-copy-this-secret", repr(store.entries))

    def test_owner_role_and_scene_cannot_replay_another_page(self):
        store, event = pages.KeyboardPageStore(), Event(admin=True)
        first = store.create(category_buttons(), event, page_cards=card_snapshots())
        others = [Event(sender="bob", admin=True), Event(session="other", admin=True),
                  Event(platform="other", admin=True), Event(admin=False)]
        other_scene = Event(admin=True)
        other_scene.message_obj.raw_message = fixtures.C2CMessage()
        others.append(other_scene)
        for other in others:
            self.assertIsNone(store.get_page(first.token, 2, other))

    def test_rejects_incomplete_oversized_or_malformed_page_cards(self):
        store, event = pages.KeyboardPageStore(), Event()
        bad = [card_snapshots(2), card_snapshots(4), "not cards"]
        for replacement in (("", ()), ("x" * (pages.MAX_CARD_CONTENT_CHARS + 1), ()),
                            ("content", "token"), ("content", [None]),
                            ("content", ["bad\ntoken"]), ("content", ["x" * 513]),
                            ("content", ["token"] * (pages.MAX_IMAGE_TOKENS + 1)),
                            ("content", (), "extra")):
            values = card_snapshots()
            values[1] = replacement
            bad.append(values)
        bad.append([("content", ["token"] * 86)] * 3)
        for values in bad:
            with self.subTest(values=str(values)[:60]):
                self.assertIsNone(store.create(category_buttons(), event, page_cards=values))
        self.assertFalse(store.entries)


class CategoryImageReplayTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        self.service = TokenService()
        self.publisher = transport.ImagePublisher(self.service, self.root / "published",
                                                  "https://example.test", ttl=60, max_tokens=8)
        self.cards = transport.CardTransport(self.publisher)
        self.cards.callbacks_enabled = True
        self.clock = [1.0]
        self.cards.keyboard_pages = pages.KeyboardPageStore(ttl=60, clock=lambda: self.clock[0])
        self.cards.install()
        self.addCleanup(self.cards.close)
        self.plugin = types.SimpleNamespace(transport=self.cards)
        self.buttons = category_buttons()
        self.sources = []
        for number, color in enumerate(("red", "green", "blue"), 1):
            path = self.root / f"category-{number}.png"
            PILImage.new("RGB", (24, 16), color).save(path)
            self.sources.append(path)
        published = await self.publisher.publish_batch([fixtures.Image(str(path)) for path in self.sources])
        self.urls = [item[0] for item in published]
        self.tokens = [url.rsplit("/", 1)[-1] for url in self.urls]
        self.snapshots = tuple((f"![图片 #{width}px #{height}px]({url})", (token,))
                               for (url, width, height), token in zip(published, self.tokens))
        event = Event()
        self.key = (event.get_platform_id(), "GroupMessage", "passive")
        self.initial = self.cards._payload("完整的十九项功能文字", self.buttons, self.key,
                                           event=event, page_cards=self.snapshots)
        self.page_token = next(iter(self.cards.keyboard_pages.entries))
        self.original_expiries = {token: self.publisher.owned[token][1] for token in self.tokens}
        for path in self.sources:
            path.unlink()

    async def replay(self, number, event=None, *, before_send=None):
        event = event or Event()
        results = [result async for result in page_handler()(self.plugin, event, self.page_token, number)]
        self.assertEqual(len(results), 1)
        event.send_buffer = results[0]
        if before_send:
            before_send()
        await event._post_send_one(results[0])
        return event.bot.api.calls[0], event

    def assert_card(self, payload, number, event):
        content = payload["markdown"]["content"]
        self.assertEqual(content, f"{self.snapshots[number - 1][0]}\n\n按钮第 {number}/3 页")
        for index, url in enumerate(self.urls, 1):
            self.assertEqual(content.count(url), int(index == number))
        self.assertNotIn("完整的十九项", content)
        self.assertNotIn("操作菜单", content)
        commands = []
        for button in actions(payload["keyboard"]):
            self.assertEqual(button["action"]["type"], 1)
            command = self.cards.callback_actions.resolve(button["action"]["data"],
                platform_id=event.get_platform_id(), scene="group",
                session=event.get_session_id(), sender=event.get_sender_id())
            self.assertIsNotNone(command)
            if not command.startswith("/菜单翻页 "):
                commands.append(command)
        expected = self.buttons[(number - 1) * pages.PAGE_SIZE:number * pages.PAGE_SIZE]
        self.assertEqual(commands, [button["command"] for button in expected])

    def assert_expired(self, payload):
        content = payload["markdown"]["content"]
        self.assertIn("过期", content)
        for url in self.urls:
            self.assertNotIn(url, content)
        self.assertNotIn("![", content)

    async def test_next_last_and_back_keep_matching_image_buttons_and_callback_event(self):
        self.assert_card(self.initial, 1, Event())
        for number in (2, 3, 1):
            event = Event()
            event.set_extra("qqofficial_interaction_event_id", f"outer-event-{number}")
            payload, event = await self.replay(number, event)
            self.assert_card(payload, number, event)
            self.assertEqual(payload["event_id"], f"outer-event-{number}")
            self.assertNotIn("msg_id", payload)
        self.assertEqual(self.service.counter, 3, "paging must reuse original published URLs")
        self.assertEqual({token: self.publisher.owned[token][1] for token in self.tokens},
                         self.original_expiries)
        self.assertEqual(len(self.cards.keyboard_pages.entries), 1)

    async def test_wrong_owner_and_page_expiry_never_expose_any_page_image(self):
        for event in (Event(sender="bob"), Event(session="other"), Event(admin=True)):
            payload, event = await self.replay(2, event)
            self.assert_expired(payload)
            self.assertNotIn(pages.PAGE_HINT_KEY, event.extras)
        self.clock[0] = 61.0
        payload, event = await self.replay(1)
        self.assert_expired(payload)
        self.assertNotIn(pages.PAGE_HINT_KEY, event.extras)

    async def test_only_selected_page_token_is_required_and_missing_file_is_rejected(self):
        self.publisher.owned.pop(self.tokens[0])
        payload, event = await self.replay(2)
        self.assert_card(payload, 2, event)
        payload, _ = await self.replay(1)
        self.assert_expired(payload)
        self.publisher.owned[self.tokens[1]][0].unlink()
        payload, _ = await self.replay(2)
        self.assert_expired(payload)

    async def test_expired_token_and_eviction_after_handler_validation_are_rejected(self):
        path, _ = self.publisher.owned[self.tokens[0]]
        self.publisher.owned[self.tokens[0]] = (path, 0.0)
        payload, _ = await self.replay(1)
        self.assert_expired(payload)
        payload, _ = await self.replay(2, before_send=lambda: self.publisher.owned.pop(self.tokens[1]))
        self.assert_expired(payload)


class CategoryRenderingTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        self.service = TokenService()
        self.publisher = transport.ImagePublisher(self.service, self.root / "published",
                                                  "https://example.test", ttl=60, max_tokens=32)
        self.cards = transport.CardTransport(self.publisher)
        self.cards.callbacks_enabled = True
        self.cards.install()
        self.addCleanup(self.cards.close)
        self.plugin = types.SimpleNamespace(transport=self.cards)
        self.drawn = []

    def draw_page(self, title, description, buttons, *, cache_dir, page, page_size):
        visible = buttons[(page - 1) * page_size:page * page_size]
        self.drawn.append((title, description, [dict(item) for item in visible], page, page_size))
        path = self.root / f"drawn-{page}.png"
        PILImage.new("RGB", (24, 16), (page * 17, page * 11, page * 7)).save(path)
        return path

    def category_event(self, *, errors=()):
        text, buttons = fixtures.menus.menu_page("光遇", is_admin=False, is_private=False)
        chain = fixtures.Chain([fixtures.Plain(text)])
        event = Event(chain, fixtures.API(errors))
        event.get_message_str = lambda: "/功能菜单 光遇"
        event.set_extra("qqofficial_interaction_event_id", "outer-category-event")
        support.set_card_hint(event, buttons=buttons)
        return event, chain, (len(buttons) + 7) // 8

    def assert_all_pages_without_keyboard(self, payload, first_token, count):
        content = payload["markdown"]["content"]
        self.assertNotIn("keyboard", payload)
        self.assertEqual(content.count("![菜单 "), count)
        positions = []
        for index in range(first_token, first_token + count):
            url = f"https://example.test/api/file/test-owned-{index}"
            self.assertEqual(content.count(url + ")"), 1)
            positions.append(content.index(url + ")"))
        self.assertEqual(positions, sorted(positions))
        self.assertEqual(payload["event_id"], "outer-category-event")
        self.assertNotIn("msg_id", payload)

    async def test_keyboard_disabled_by_config_or_prior_rejection_keeps_all_page_images(self):
        for mode in ("config", "remembered"):
            with self.subTest(mode=mode):
                event, chain, total = self.category_event()
                self.cards.keyboard = mode != "config"
                key = (event.get_platform_id(), "GroupMessage", "passive")
                if mode == "remembered":
                    self.cards.disabled_keyboard.add(key)
                first_token = self.service.counter + 1
                with patch.object(transport, "render_command_menu", side_effect=self.draw_page):
                    await event._post_send_one(chain)
                self.assertEqual(len(event.bot.api.calls), 1)
                self.assert_all_pages_without_keyboard(event.bot.api.calls[0], first_token, total)

    async def test_explicit_keyboard_rejection_retries_all_images_and_remembers_fallback(self):
        event, chain, total = self.category_event(errors=[fixtures.ServerError("not allowd custom keyborad")])
        with patch.object(transport, "render_command_menu", side_effect=self.draw_page):
            await event._post_send_one(chain)
            self.assertEqual(len(event.bot.api.calls), 2)
            self.assertIn("keyboard", event.bot.api.calls[0])
            self.assertEqual(event.bot.api.calls[0]["markdown"]["content"].count("![菜单 "), 1)
            self.assert_all_pages_without_keyboard(event.bot.api.calls[1], 1, total)
            later, later_chain, later_total = self.category_event()
            await later._post_send_one(later_chain)
            self.assertEqual(len(later.bot.api.calls), 1)
            self.assert_all_pages_without_keyboard(later.bot.api.calls[0], total + 1, later_total)

    async def test_markdown_rejection_sends_every_generated_image_with_callback_event(self):
        event, chain, total = self.category_event(errors=[fixtures.ServerError("不允许发送原生 markdown")])

        def split_images(fallback):
            self.assertTrue(all(isinstance(item, fixtures.Image) for item in fallback.chain))
            return [fixtures.Chain([image]) for image in fallback.chain]

        def parse_image(part):
            image = part.chain[0]
            return "", image.path, None, None, None, None, None

        upload = AsyncMock(side_effect=lambda helper, path, image_type, **destination: {"file_info": path})
        with patch.object(transport, "render_command_menu", side_effect=self.draw_page), \
             patch.object(fixtures.OriginalEvent, "_split_message_chain_by_media", side_effect=split_images) as splitter, \
             patch.object(fixtures.OriginalEvent, "_parse_to_qqofficial", AsyncMock(side_effect=parse_image)), \
             patch.object(fixtures.OriginalEvent, "upload_group_and_c2c_image", upload, create=True):
            await event._post_send_one(chain)
        self.assertEqual(len(splitter.call_args.args[0].chain), total)
        self.assertEqual(upload.await_count, total)
        self.assertEqual(len(event.bot.api.calls), total + 1)
        self.assertIn("markdown", event.bot.api.calls[0])
        for number, payload in enumerate(event.bot.api.calls[1:], 1):
            self.assertNotIn("markdown", payload)
            self.assertEqual(payload["msg_type"], 7)
            self.assertEqual(Path(payload["media"]["file_info"]).name, f"drawn-{number}.png")
            self.assertEqual(payload["event_id"], "outer-category-event")
            self.assertNotIn("msg_id", payload)
        self.assertTrue(event.marked_sent)

    def assert_plain_help_submission(self, submission, total):
        fallback = submission.args[3]
        self.assertEqual(len(fallback.chain), total)
        self.assertTrue(all(isinstance(item, fixtures.Image) for item in fallback.chain))
        self.assertEqual([Path(item.path).name for item in fallback.chain],
                         [f"drawn-{number}.png" for number in range(1, total + 1)])
        self.assertEqual(submission.kwargs["event_id"], "outer-category-event")

    async def test_later_help_after_markdown_rejection_still_sends_every_page_as_media(self):
        first, first_chain, total = self.category_event(errors=[fixtures.ServerError("不允许发送原生 markdown")])
        later, later_chain, later_total = self.category_event()
        with patch.object(transport, "render_command_menu", side_effect=self.draw_page) as renderer, \
             patch.object(self.cards, "_send_plain_session", AsyncMock(return_value=True)) as send_media:
            await first._post_send_one(first_chain)
            self.assertIn((first.get_platform_id(), "GroupMessage", "passive"), self.cards.disabled_markdown)
            await later._post_send_one(later_chain)
        self.assertEqual(send_media.await_count, 2)
        self.assert_plain_help_submission(send_media.call_args_list[0], total)
        self.assert_plain_help_submission(send_media.call_args_list[1], later_total)
        self.assertEqual(renderer.call_count, total + later_total)
        self.assertEqual(len(first.bot.api.calls), 1)
        self.assertEqual(later.bot.api.calls, [], "known Markdown rejection must not be retried")
        self.assertTrue(later.marked_sent)

    async def test_explicit_plain_help_still_sends_every_page_as_media(self):
        event, chain, total = self.category_event()
        chain.use_markdown_ = False
        with patch.object(transport, "render_command_menu", side_effect=self.draw_page) as renderer, \
             patch.object(self.cards, "_send_plain_session", AsyncMock(return_value=True)) as send_media:
            await event._post_send_one(chain)
        self.assertEqual(renderer.call_count, total)
        send_media.assert_awaited_once()
        self.assert_plain_help_submission(send_media.call_args, total)
        self.assertEqual(event.bot.api.calls, [])
        self.assertTrue(event.marked_sent)

    async def test_plain_help_send_failure_is_not_caught_as_render_failure_or_retried(self):
        for mode, failure in (("explicit", OSError("uncertain media delivery")),
                              ("remembered", RuntimeError("uncertain media delivery"))):
            with self.subTest(mode=mode):
                event, chain, total = self.category_event()
                if mode == "explicit":
                    chain.use_markdown_ = False
                else:
                    self.cards.disabled_markdown.add((event.get_platform_id(), "GroupMessage", "passive"))
                with patch.object(transport, "render_command_menu", side_effect=self.draw_page), \
                     patch.object(self.cards, "_send_plain_session", AsyncMock(side_effect=failure)) as send_media:
                    with self.assertRaisesRegex(type(failure), "uncertain media delivery"):
                        await event._post_send_one(chain)
                send_media.assert_awaited_once()
                self.assert_plain_help_submission(send_media.call_args, total)
                self.assertFalse(event.marked_sent)

    async def test_category_entry_renders_every_filtered_page_and_navigation_reuses_it(self):
        text, buttons = fixtures.menus.menu_page("光遇", is_admin=False, is_private=False)
        chain = fixtures.Chain([fixtures.Plain(text)])
        event = Event(chain)
        event.get_message_str = lambda: "#官方菜单 sky"
        support.set_card_hint(event, buttons=buttons)
        expected = transport.normalize_buttons(buttons)
        total = (len(expected) + 7) // 8
        self.assertGreater(total, 2)
        with patch.object(transport, "render_command_menu", side_effect=self.draw_page) as renderer:
            await event._post_send_one(chain)
            self.assertEqual(renderer.call_count, total)
            token = next(iter(self.cards.keyboard_pages.entries))
            initial = event.bot.api.calls[0]
            self.assertNotIn(text, initial["markdown"]["content"])
            for number in range(1, total + 1):
                selected = self.cards.keyboard_pages.get_page(token, number, event)
                drawn = self.drawn[number - 1]
                self.assertEqual(drawn[3:], (number, 8))
                self.assertEqual(drawn[2], expected[(number - 1) * 8:number * 8])
                self.assertEqual(drawn[2], [item for item in selected.buttons
                                           if item["command"] not in selected.navigation_commands])
                self.assertEqual(len(selected.image_tokens), 1)
                self.assertTrue(self.publisher.has_tokens(selected.image_tokens))
            for number in (2, total, 1):
                replay_event = Event()
                replay_event.get_message_str = lambda: "/菜单翻页"
                results = [result async for result in page_handler()(self.plugin, replay_event, token, number)]
                replay_event.send_buffer = results[0]
                await replay_event._post_send_one(results[0])
                selected = self.cards.keyboard_pages.get_page(token, number, replay_event)
                self.assertEqual(replay_event.bot.api.calls[0]["markdown"]["content"], selected.text)
            self.assertEqual(renderer.call_count, total, "callbacks must not redraw the whole category")
            self.assertEqual(self.service.counter, total)

    async def test_nine_button_category_stays_on_one_complete_image(self):
        text, buttons = fixtures.menus.menu_page("JM", is_admin=True, is_private=False)
        self.assertEqual(len(buttons), 9)
        chain = fixtures.Chain([fixtures.Plain(text)])
        event = Event(chain, admin=True)
        event.get_message_str = lambda: "/功能菜单 jm"
        support.set_card_hint(event, buttons=buttons)
        with patch.object(transport, "render_command_menu", side_effect=self.draw_page) as renderer:
            await event._post_send_one(chain)
        self.assertEqual(renderer.call_count, 1)
        self.assertEqual(self.drawn[0][2], transport.normalize_buttons(buttons))
        self.assertEqual(self.drawn[0][3:], (1, 10))
        self.assertFalse(self.cards.keyboard_pages.entries)
        self.assertIn("![菜单", event.bot.api.calls[0]["markdown"]["content"])
        self.assertEqual(len(actions(event.bot.api.calls[0]["keyboard"])), 9)

    async def test_existing_help_artwork_is_retained_instead_of_regenerated(self):
        path = self.root / "upstream-help.png"
        PILImage.new("RGB", (24, 16), "purple").save(path)
        chain = fixtures.Chain([fixtures.Plain("插件原有帮助说明"), fixtures.Image(str(path))])
        event = Event(chain)
        event.get_message_str = lambda: "/功能菜单 光遇"
        support.set_card_hint(event, title="原插件帮助图", buttons=category_buttons())
        with patch.object(transport, "render_command_menu", side_effect=AssertionError("must preserve artwork")), \
             patch.object(transport, "render_text_menu", side_effect=AssertionError("must preserve artwork")):
            await event._post_send_one(chain)
        token = next(iter(self.cards.keyboard_pages.entries))
        first = self.cards.keyboard_pages.get_page(token, 1, event)
        second = self.cards.keyboard_pages.get_page(token, 2, event)
        self.assertEqual(first.card_content, second.card_content)
        self.assertEqual(first.image_tokens, second.image_tokens)
        self.assertIn("插件原有帮助说明", first.card_content)
        self.assertIn("## 原插件帮助图", first.card_content)
        self.assertEqual(self.service.counter, 1)


if __name__ == "__main__":
    unittest.main()
