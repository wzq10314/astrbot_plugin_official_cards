"""Regressions found by an independent local transport review."""

import ast
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image as PILImage
import test_transport as fixtures


class Service:
    def __init__(self):
        self.tokens = {}
        self.counter = 0

    async def register_file(self, path, timeout=None):
        self.counter += 1
        token = str(self.counter)
        self.tokens[token] = path
        return token

    async def handle_file(self, token):
        return self.tokens.pop(token)


def snapshot_fallback():
    """Use the real core retry body, rather than a permissive transport mock."""
    source = Path(__file__).resolve().parents[3] / "core/astrbot/core/platform/sources/qqofficial/qqofficial_message_event.py"
    tree = ast.parse(source.read_text(encoding="utf-8-sig"))
    cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "QQOfficialMessageEvent")
    method = next(node for node in cls.body if isinstance(node, ast.AsyncFunctionDef) and node.name == "_send_with_markdown_fallback")
    method.decorator_list = []
    namespace = {
        "_QQOFFICIAL_SEND_API_ERRORS": (fixtures.ServerError, fixtures.ForbiddenError),
        "botpy": fixtures.transport.botpy,
        "logger": fixtures.types.SimpleNamespace(info=lambda *a: None, warning=lambda *a: None),
        "QQOfficialMessageEvent": fixtures.types.SimpleNamespace(
            MARKDOWN_NOT_ALLOWED_ERROR="不允许发送原生 markdown",
        ),
    }
    exec(compile(ast.fix_missing_locations(ast.Module(body=[method], type_ignores=[])), str(source), "exec"), namespace)
    return namespace["_send_with_markdown_fallback"]


class CrossReviewTests(unittest.IsolatedAsyncioTestCase):
    async def test_render_never_returns_links_evicted_during_the_same_card(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            publisher = fixtures.transport.ImagePublisher(Service(), directory / "cache", "https://example.test", max_tokens=8)
            publisher.install()
            try:
                components = []
                for index in range(10):
                    path = directory / f"{index}.png"
                    PILImage.new("RGB", (2, 2), (index, 0, 0)).save(path)
                    components.append(fixtures.Image(str(path)))
                cards = fixtures.transport.CardTransport(publisher)
                try:
                    content, _ = await cards.render(fixtures.Chain(components), {})
                except ValueError:
                    # The sending wrapper catches a preparation rejection and
                    # falls back to the original image components.
                    self.assertFalse(publisher.owned)
                    return
                if content is not None:
                    import re
                    tokens = re.findall(r"/api/file/([^)]*)\)", content)
                    self.assertTrue(tokens)
                    self.assertTrue(all(token in publisher.owned for token in tokens),
                                    "a rendered card includes tokens revoked before the message was sent")
            finally:
                publisher.close()

    async def test_plain_event_fallback_never_uses_core_proactive_retry(self):
        core_send = snapshot_fallback()

        async def core_original(event, chain, stream=None):
            return await core_send(
                lambda payload: event.bot.api.post_group_message(group_openid="group-openid", **payload),
                {"content": "plain", "msg_id": "passive-message", "msg_type": 0},
                "plain",
            )

        with patch.object(fixtures.OriginalEvent, "_post_send_one", core_original):
            cards = fixtures.transport.CardTransport(fixtures.Publisher())
            cards.install()
            try:
                api = fixtures.API([
                    fixtures.ServerError("不允许发送原生 markdown"),
                    fixtures.ServerError("unknown server failure"),
                    None,
                ])
                chain = fixtures.Chain([fixtures.Plain("plain")])
                event = fixtures.Event(chain, api)
                with self.assertRaises(fixtures.ServerError):
                    await event._post_send_one(chain)
                self.assertEqual(2, len(api.calls))
                self.assertEqual("passive-message", api.calls[-1]["msg_id"])
            finally:
                cards.close()

    def test_auto_submit_navigation_requires_an_exact_static_category(self):
        self.assertFalse(fixtures.transport._safe_enter("/功能菜单 资讯\n/禁言 1"))


if __name__ == "__main__":
    unittest.main()
