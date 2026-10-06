"""Replay actual published help images without retaining their source files."""
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image as PILImage

import test_transport as fixtures
from test_keyboard_pages import Event, actions, page_handler, pages, support


transport = fixtures.transport


class TokenService:
    def __init__(self):
        self.tokens, self.counter = {}, 0

    async def register_file(self, path, timeout=None):
        self.counter += 1
        token = f"test-owned-{self.counter}"
        self.tokens[token] = path
        return token

    async def handle_file(self, token):
        return self.tokens.pop(token)


def help_buttons(count=35):
    return [{"label": f"帮助操作{index}", "callback": f"#王者主页{10001 + index}"}
            for index in range(count)]


class HelpCardReplayTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        self.source = self.root / "help.png"
        PILImage.new("RGB", (24, 16), "blue").save(self.source)
        self.service = TokenService()
        self.publisher = transport.ImagePublisher(self.service, self.root / "cache",
                                                  "https://example.test", ttl=60, max_tokens=8)
        self.cards = transport.CardTransport(self.publisher)
        self.cards.callbacks_enabled = True
        self.page_clock = [0.0]
        self.cards.keyboard_pages = pages.KeyboardPageStore(ttl=60, clock=lambda: self.page_clock[0])
        self.cards.install()
        self.addCleanup(self.cards.close)
        self.plugin = types.SimpleNamespace(transport=self.cards)

        chain = fixtures.Chain([fixtures.Plain("原始帮助说明"), fixtures.Image(str(self.source))])
        event = Event(chain)
        support.set_card_hint(event, title="王者帮助", buttons=help_buttons())
        await event._post_send_one(chain)
        self.initial = event.bot.api.calls[0]
        self.page_token = next(iter(self.cards.keyboard_pages.entries))
        self.first = self.cards.keyboard_pages.get_page(self.page_token, 1, event)
        self.image_token = self.first.image_tokens[0]
        self.image_url = f"https://example.test/api/file/{self.image_token}"
        self.original_expiry = self.publisher.owned[self.image_token][1]
        self.original_content = self.first.card_content
        self.source.unlink()

    async def replay(self, number, event=None):
        event = event or Event()
        results = [result async for result in page_handler()(self.plugin, event, self.page_token, number)]
        self.assertEqual(len(results), 1)
        event.send_buffer = results[0]
        # Even a carried title must not be inserted twice on replay.
        support.set_card_hint(event, title="王者帮助")
        await event._post_send_one(results[0].derive(results[0].chain))
        return event.bot.api.calls[0], event

    def assert_no_card_leak(self, payload):
        content = payload["markdown"]["content"]
        self.assertNotIn(self.image_url, content)
        self.assertNotIn("原始帮助说明", content)
        self.assertNotIn("![", content)
        self.assertIn("过期", content)

    async def test_page_two_and_back_keep_original_image_text_and_single_title(self):
        self.assertEqual(self.first.total, 5)
        self.assertFalse(self.source.exists())
        self.assertTrue(self.publisher.has_tokens((self.image_token,)))
        published_copy = Path(await self.service.handle_file(self.image_token))
        self.assertTrue(published_copy.is_file())
        self.assertNotEqual(published_copy, self.source)
        seen = []
        for number in range(1, self.first.total + 1):
            page = self.cards.keyboard_pages.get_page(self.page_token, number, Event())
            seen.extend(button["command"] for button in page.buttons
                        if button["command"] not in page.navigation_commands)
        self.assertEqual(seen, [button["callback"] for button in help_buttons()])

        for number in (2, 5, 1):
            outgoing, _ = await self.replay(number)
            content = outgoing["markdown"]["content"]
            self.assertEqual(content, f"{self.original_content}\n\n按钮第 {number}/5 页")
            self.assertEqual(content.count(self.image_url), 1)
            self.assertEqual(content.count("## 王者帮助"), 1)
            self.assertEqual(content.count("原始帮助说明"), 1)
            self.assertNotIn("操作菜单", content)
            self.assertNotIn("#王者主页", content)
            self.assertTrue(all(button["action"]["type"] == 1 for button in actions(outgoing["keyboard"])))
        self.assertEqual(self.service.counter, 1, "navigation must not republish an image")
        self.assertEqual(self.publisher.owned[self.image_token][1], self.original_expiry)
        self.assertEqual(len(self.cards.keyboard_pages.entries), 1)

    async def test_wrong_owner_and_expired_page_never_replay_the_image(self):
        wrong_owner, event = await self.replay(2, Event(sender="bob"))
        self.assert_no_card_leak(wrong_owner)
        self.assertNotIn(pages.PAGE_HINT_KEY, event.extras)
        self.page_clock[0] = 60.0
        expired, event = await self.replay(1)
        self.assert_no_card_leak(expired)
        self.assertNotIn(pages.PAGE_HINT_KEY, event.extras)
        self.assertTrue(self.publisher.has_tokens((self.image_token,)))

    async def test_expired_image_rejects_replay_without_extending_its_lifetime(self):
        before = dict(self.publisher.owned)
        with patch.object(transport.time, "monotonic", return_value=self.original_expiry - 1):
            self.assertTrue(self.publisher.has_tokens((self.image_token,)))
        with patch.object(transport.time, "monotonic", return_value=self.original_expiry):
            self.assertFalse(self.publisher.has_tokens((self.image_token,)))
        self.assertEqual(self.publisher.owned, before)
        path, _ = self.publisher.owned[self.image_token]
        self.publisher.owned[self.image_token] = (path, 0.0)
        expired, event = await self.replay(2)
        self.assert_no_card_leak(expired)
        self.assertNotIn(pages.PAGE_HINT_KEY, event.extras)

    async def test_token_eviction_rejects_replay_even_when_cached_file_remains(self):
        cached_path = self.publisher.owned[self.image_token][0]
        replacement_source = self.root / "replacement.png"
        PILImage.new("RGB", (24, 16), "blue").save(replacement_source)
        for _ in range(self.publisher.max_tokens):
            await self.publisher.publish(fixtures.Image(str(replacement_source)))
        self.assertNotIn(self.image_token, self.publisher.owned)
        self.assertTrue(cached_path.is_file())
        outgoing, _ = await self.replay(2)
        self.assert_no_card_leak(outgoing)

    async def test_transport_rechecks_image_eviction_after_handler_validation(self):
        event = Event()
        results = [result async for result in page_handler()(self.plugin, event, self.page_token, 2)]
        self.assertIn(self.image_url, results[0].chain[0].text)
        self.publisher.owned.pop(self.image_token)
        event.send_buffer = results[0]
        await event._post_send_one(results[0])
        self.assert_no_card_leak(event.bot.api.calls[0])


class CompleteHelpButtonTests(unittest.TestCase):
    def test_nested_normalization_and_hint_preserve_more_than_25_actions(self):
        original = help_buttons(70)
        nested = [original[:18], [original[18:37], [original[37:55]]], original[55:]]
        normalized = transport.normalize_buttons(nested)
        self.assertEqual([item["command"] for item in normalized],
                         [item["callback"] for item in original])
        hints = fixtures.menus.buttons_for_event(Event(), {"buttons": original})
        self.assertEqual(hints, original)
        store, owner = pages.KeyboardPageStore(), Event()
        first = store.create(transport.normalize_buttons(hints), owner)
        seen = []
        for number in range(1, first.total + 1):
            page = store.get_page(first.token, number, owner)
            seen.extend(item["command"] for item in page.buttons
                        if item["command"] not in page.navigation_commands)
        self.assertEqual(seen, [item["callback"] for item in original])


if __name__ == "__main__":
    unittest.main()
