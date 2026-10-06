"""Contract tests with only network/platform boundaries stubbed."""
import importlib
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch


def module(name, **values):
    result = types.ModuleType(name)
    result.__dict__.update(values)
    sys.modules[name] = result
    return result


class Plain:
    def __init__(self, text): self.text = text


class Image:
    def __init__(self, path): self.path = path
    async def convert_to_file_path(self): return self.path
    @staticmethod
    def fromFileSystem(path): return Image(path)


class Node:
    def __init__(self, content): self.content = content


class Nodes:
    def __init__(self, nodes): self.nodes = nodes


class At: pass
class AtAll: pass
class Reply: pass
class Video: pass


class Chain:
    def __init__(self, chain, use_markdown_=None):
        self.chain = chain
        self.use_markdown_ = use_markdown_
    def derive(self, chain): return Chain(chain, self.use_markdown_)


class BaseEvent:
    async def send(self, chain): self.marked_sent = True


class OriginalEvent(BaseEvent):
    async def _post_send_one(self, chain, stream=None):
        self.original_calls.append((chain, self.send_buffer.use_markdown_, stream))
        return {"id": "fallback"}
    @staticmethod
    def _split_message_chain_by_media(chain): return [chain]
    @staticmethod
    async def _parse_to_qqofficial(chain):
        return ("".join(c.text for c in chain.chain if isinstance(c, Plain)), None, None, None, None, None, None)


class OriginalAdapter:
    async def _send_by_session_common(self, session, chain):
        self.original_calls.append((session, chain))


class GroupMessage: pass
class C2CMessage: pass
class DirectMessage: pass
class Message: pass
class ServerError(Exception): pass
class ForbiddenError(Exception): pass


def setup_imports():
    log = types.SimpleNamespace(info=lambda *a, **k: None)
    module("botpy", errors=module("botpy.errors", ServerError=ServerError, ForbiddenError=ForbiddenError),
           message=module("botpy.message", GroupMessage=GroupMessage, C2CMessage=C2CMessage,
                          DirectMessage=DirectMessage, Message=Message))
    for name in ("astrbot", "astrbot.core", "astrbot.core.platform", "astrbot.core.platform.sources", "astrbot.core.platform.sources.qqofficial"):
        module(name)
    module("astrbot.api", logger=log)
    module("astrbot.api.event", MessageChain=Chain)
    module("astrbot.api.message_components", Plain=Plain, Image=Image, Node=Node, Nodes=Nodes, At=At, AtAll=AtAll, Reply=Reply)
    module("astrbot.core.platform.astr_message_event", AstrMessageEvent=BaseEvent)
    module("astrbot.core.platform.sources.qqofficial.qqofficial_message_event", QQOfficialMessageEvent=OriginalEvent)
    module("astrbot.core.platform.sources.qqofficial.qqofficial_platform_adapter", QQOfficialPlatformAdapter=OriginalAdapter)
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


setup_imports()
transport = importlib.import_module("astrbot_plugin_official_cards.transport")
menus = importlib.import_module("astrbot_plugin_official_cards.menus")


class Publisher:
    def install(self): self.active = True
    def close(self): self.active = False
    async def publish(self, component): return "https://example.test/api/file/token", 600, 400
    async def publish_batch(self, components): return [await self.publish(c) for c in components]


class API:
    def __init__(self, errors=()): self.calls, self.errors = [], list(errors)
    async def post_group_message(self, **payload):
        self.calls.append(payload)
        if self.errors:
            error = self.errors.pop(0)
            if error: raise error
        return {"id": "real-receipt"}
    post_c2c_message = post_group_message
    post_message = post_group_message
    post_dms = post_group_message


class Event(OriginalEvent):
    def __init__(self, chain, api):
        source = GroupMessage()
        source.group_openid = "group-openid"
        self.message_obj = types.SimpleNamespace(raw_message=source, message_id="passive-message")
        self.bot = types.SimpleNamespace(api=api)
        self.send_buffer, self.original_calls, self.marked_sent = chain, [], False
    def get_platform_id(self): return "official-test"
    def get_extra(self, key, default=None): return default
    def get_message_str(self): return "新闻"
    def is_admin(self): return False


class Adapter(OriginalAdapter):
    def __init__(self, api, scene="group", msg_id="passive-message"):
        self.client = types.SimpleNamespace(api=api)
        self._session_scene = {"target": scene}
        self._session_last_message_id = {"target": msg_id} if msg_id else {}
        self._allow_group_proactive_send = True
        self.use_markdown_default = True
        self.original_calls = []
    def meta(self): return types.SimpleNamespace(id="official-test")
    def _extract_message_id(self, value): return value.get("id")
    def remember_session_message_id(self, key, value): self._session_last_message_id[key] = value


class TransportTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.cards = transport.CardTransport(Publisher())
        self.cards.install()
    async def asyncTearDown(self): self.cards.close()

    async def test_native_image_text_and_keyboard(self):
        chain, api = Chain([Plain("今日资讯"), Image("image.png")]), API()
        event = Event(chain, api)
        await event._post_send_one(chain)
        self.assertEqual(len(api.calls), 1)
        payload = api.calls[0]
        self.assertEqual(payload["msg_type"], 2)
        self.assertIn("今日资讯", payload["markdown"]["content"])
        self.assertIn("![图片 #600px #400px]", payload["markdown"]["content"])
        self.assertIn("keyboard", payload)
        self.assertEqual(payload["msg_id"], "passive-message")
        self.assertTrue(event.marked_sent)

    async def test_keyboard_reject_retries_once_without_keyboard(self):
        chain = Chain([Plain("text")])
        api = API([ServerError("not allowd custom keyborad"), None])
        event = Event(chain, api)
        await event._post_send_one(chain)
        self.assertEqual(len(api.calls), 2)
        self.assertNotIn("keyboard", api.calls[-1])
        await event._post_send_one(chain)
        self.assertNotIn("keyboard", api.calls[-1])

    async def test_markdown_reject_restores_images_and_plain_flag(self):
        image = Image("image.png")
        chain = Chain([Plain("text"), image])
        api = API([ServerError("不允许发送原生 markdown")])
        event = Event(chain, api)
        parse = AsyncMock(return_value=("text", "image-bytes", None, None, None, None, None))
        upload = AsyncMock(return_value={"file_info": "uploaded"})
        with patch.object(OriginalEvent, "_parse_to_qqofficial", parse), \
             patch.object(OriginalEvent, "upload_group_and_c2c_image", upload, create=True):
            await event._post_send_one(chain)
        self.assertEqual(len(api.calls), 2)
        self.assertIs(parse.call_args.args[0].chain[1], image)
        self.assertEqual(api.calls[-1]["msg_type"], 7)
        self.assertEqual(api.calls[-1]["msg_id"], "passive-message")
        self.assertNotIn("markdown", api.calls[-1])
        self.assertIs(event.send_buffer, chain)

    async def test_plain_fallback_generic_error_is_not_retried_as_proactive(self):
        chain = Chain([Plain("text")])
        api = API([ServerError("不允许发送原生 markdown"), ServerError("temporary server failure")])
        event = Event(chain, api)
        with self.assertRaises(ServerError): await event._post_send_one(chain)
        self.assertEqual(len(api.calls), 2)
        self.assertEqual(api.calls[1]["msg_id"], "passive-message")
        self.assertEqual(event.original_calls, [])

    async def test_timeout_never_retries_or_duplicates(self):
        chain = Chain([Plain("text")])
        api = API([TimeoutError("uncertain delivery")])
        event = Event(chain, api)
        with self.assertRaises(TimeoutError): await event._post_send_one(chain)
        self.assertEqual(len(api.calls), 1)
        self.assertEqual(event.original_calls, [])

    async def test_unknown_api_error_never_retries(self):
        chain = Chain([Plain("text")])
        api = API([ServerError("msg limit exceed")])
        with self.assertRaises(ServerError): await Event(chain, api)._post_send_one(chain)
        self.assertEqual(len(api.calls), 1)

    async def test_none_receipt_is_unconfirmed_and_never_retried(self):
        for use_markdown in (None, False):
            chain = Chain([Plain("text")], use_markdown)
            api = API()
            api.post_group_message = AsyncMock(return_value=None)
            event = Event(chain, api)
            with self.assertRaisesRegex(RuntimeError, "delivery is unconfirmed"):
                await event._post_send_one(chain)
            api.post_group_message.assert_awaited_once()
            self.assertFalse(event.marked_sent)
            self.assertEqual(event.original_calls, [])

    async def test_forward_flatten_keeps_order(self):
        components = [Nodes([Node([Plain("first"), Image("a")]), Node([Plain("second")])])]
        chain, api = Chain(components), API()
        await Event(chain, api)._post_send_one(chain)
        content = api.calls[0]["markdown"]["content"]
        self.assertLess(content.index("first"), content.index("![图片"))
        self.assertLess(content.index("![图片"), content.index("second"))

    async def test_video_reuses_core_parser_and_stream_keeps_original_transport(self):
        chain, api = Chain([Video()]), API()
        event = Event(chain, api)
        parse = AsyncMock(return_value=("", None, None, None, "/tmp/video.mp4", None, None))
        upload = AsyncMock(return_value={"file_info": "video"})
        with patch.object(OriginalEvent, "_parse_to_qqofficial", parse), \
             patch.object(OriginalEvent, "upload_group_and_c2c_media", upload, create=True):
            await event._post_send_one(chain)
        self.assertEqual(api.calls[0]["msg_type"], 7)
        self.assertEqual(upload.call_args.args[1:], ("/tmp/video.mp4", 2))
        stream = {"state": 1}
        await event._post_send_one(Chain([Plain("delta")]), stream)
        self.assertIs(event.original_calls[-1][2], stream)
        self.assertEqual(len(api.calls), 1)

    async def test_proactive_routing_preserves_no_invented_passive_id(self):
        adapter, api = Adapter(API(), msg_id=None), None
        api = adapter.client.api
        session = types.SimpleNamespace(session_id="target", message_type=types.SimpleNamespace(name="GROUP_MESSAGE"))
        await adapter._send_by_session_common(session, Chain([Plain("notification"), Image("a")]))
        self.assertNotIn("msg_id", api.calls[0])
        self.assertEqual(api.calls[0]["group_openid"], "target")
        self.assertNotIn("target", adapter._session_last_message_id)

    async def test_channel_without_passive_id_uses_existing_policy(self):
        adapter = Adapter(API(), scene="channel", msg_id=None)
        session = types.SimpleNamespace(session_id="target", message_type=types.SimpleNamespace(name="GROUP_MESSAGE"))
        await adapter._send_by_session_common(session, Chain([Plain("notification")]))
        self.assertEqual(adapter.client.api.calls, [])
        self.assertEqual(len(adapter.original_calls), 0)

    async def test_opaque_group_openid_underscores_preserved_in_native_and_fallback(self):
        for plain in (False, True):
            adapter = Adapter(API())
            adapter._session_scene = {"opaque_group_id": "group"}
            session = types.SimpleNamespace(session_id="opaque_group_id", message_type=types.SimpleNamespace(name="GROUP_MESSAGE"))
            await adapter._send_by_session_common(session, Chain([Plain("text")], False if plain else None))
            self.assertEqual(adapter.client.api.calls[0]["group_openid"], "opaque_group_id")

    async def test_group_scene_never_guessed_from_openid_suffix(self):
        adapter = Adapter(API())
        session = types.SimpleNamespace(session_id="another_target", message_type=types.SimpleNamespace(name="GROUP_MESSAGE"))
        await adapter._send_by_session_common(session, Chain([Plain("text")]))
        self.assertEqual(adapter.client.api.calls, [])
        self.assertEqual(adapter.original_calls, [])

    async def test_known_legacy_zero_prefix_only(self):
        adapter = Adapter(API())
        session = types.SimpleNamespace(session_id="0_target", message_type=types.SimpleNamespace(name="GROUP_MESSAGE"))
        await adapter._send_by_session_common(session, Chain([Plain("text")]))
        self.assertEqual(adapter.client.api.calls[0]["group_openid"], "target")

    async def test_passive_channel_retains_inbound_message_id(self):
        adapter = Adapter(API(), scene="channel", msg_id="inbound-user-message")
        session = types.SimpleNamespace(session_id="target", message_type=types.SimpleNamespace(name="GROUP_MESSAGE"))
        await adapter._send_by_session_common(session, Chain([Plain("text")]))
        self.assertEqual(adapter.client.api.calls[0]["msg_id"], "inbound-user-message")
        self.assertEqual(adapter._session_last_message_id["target"], "inbound-user-message")

    async def test_c2c_subscription_remains_proactive_without_stale_reply_id(self):
        adapter = Adapter(API(), scene="friend", msg_id="stale")
        session = types.SimpleNamespace(session_id="target", message_type=types.SimpleNamespace(name="FRIEND_MESSAGE"))
        await adapter._send_by_session_common(session, Chain([Plain("notification")]))
        self.assertEqual(adapter.client.api.calls[0]["openid"], "target")
        self.assertNotIn("msg_id", adapter.client.api.calls[0])

    async def test_file_fallback_reuses_core_upload_signature_and_exact_target(self):
        adapter = Adapter(API())
        adapter._session_scene = {"opaque_group_id": "group"}
        session = types.SimpleNamespace(session_id="opaque_group_id", message_type=types.SimpleNamespace(name="GROUP_MESSAGE"))
        parse = AsyncMock(return_value=("", None, None, None, None, "/tmp/sample.bin", "sample.bin"))
        upload = AsyncMock(return_value={"file_info": "uploaded"})
        with patch.object(OriginalEvent, "_parse_to_qqofficial", parse), \
             patch.object(OriginalEvent, "upload_group_and_c2c_media", upload, create=True):
            await adapter._send_by_session_common(session, Chain([Video()], False))
        self.assertEqual(upload.call_args.args[1:], ("/tmp/sample.bin", 4))
        self.assertEqual(upload.call_args.kwargs, {"file_name": "sample.bin", "group_openid": "opaque_group_id"})
        self.assertIs(upload.call_args.args[0].bot, adapter.client)
        self.assertEqual(adapter.client.api.calls[0]["group_openid"], "opaque_group_id")
        self.assertEqual(adapter.client.api.calls[0]["msg_type"], 7)
        self.assertEqual(adapter.client.api.calls[0]["content"], " ")

    async def test_dynamic_buttons_survive_core_derived_chunk(self):
        original = Chain([Plain("text")])
        original.qqofficial_buttons = [[{"text": "选择账号", "callback": "#选择账号 1"}]]
        derived = original.derive(original.chain)
        self.assertFalse(hasattr(derived, "qqofficial_buttons"))
        event, api = Event(original, API()), None
        api = event.bot.api
        await event._post_send_one(derived)
        action = api.calls[0]["keyboard"]["content"]["rows"][0]["buttons"][0]["action"]
        self.assertEqual(action["data"], "#选择账号 1")
        self.assertFalse(action["enter"])

    async def test_patch_reversible(self):
        wrapper = OriginalEvent._post_send_one
        original = wrapper._official_cards_original
        self.cards.close()
        self.assertIs(OriginalEvent._post_send_one, original)

    def test_dynamic_mutations_do_not_auto_submit(self):
        buttons = transport.normalize_buttons([[{"text": "删除", "callback": "#删除账号"},
                                                {"label": "禁言", "command": "/禁言 123", "enter": True}]])
        self.assertTrue(all(not button["enter"] for button in buttons))
        keyboard = transport.build_keyboard([{ "label": "菜单", "command": "/功能菜单", "enter": True}])
        self.assertTrue(keyboard["content"]["rows"][0]["buttons"][0]["action"]["enter"])
        self.assertFalse(transport._safe_enter("/功能菜单 未知分类\n/禁言 123"))

    def test_menu_covers_original_and_resource_families(self):
        self.assertEqual(len(menus.FAMILIES), 17)
        text, buttons = menus.menu_page()
        self.assertEqual(len(buttons), 17)
        self.assertTrue({'光遇', 'Pixiv', 'JM', 'Pica'}.issubset(menus.FAMILIES))
        # 1.0.12 describes the supported group-management permissions explicitly.
        self.assertIn("群管需接口权限及机器人群管理员身份", text)
        self.assertIn("资料卡点赞和群消息贴表情仍会明确提示不支持", text)

    def test_member_menus_hide_all_admin_memory_commands_and_text(self):
        for category in ("记忆", "学习"):
            text, buttons = menus.menu_page(category, is_admin=False)
            self.assertNotIn("/lmem", text)
            self.assertNotIn("/learning_status", text)
            self.assertEqual([b["command"] for b in buttons], ["/功能菜单"])

    def test_family_aliases_match_safe_commands(self):
        event = Event(Chain([]), API())
        self.assertEqual(menus.buttons_for_event(event, {"family": "sky"})[0]["command"], "/光遇帮助")


class TokenTests(unittest.IsolatedAsyncioTestCase):
    async def test_oversized_card_batch_rejected_before_any_token_is_published(self):
        with tempfile.TemporaryDirectory() as folder:
            service = types.SimpleNamespace(handle_file=lambda token: None, register_file=AsyncMock())
            publisher = transport.ImagePublisher(service, folder, "https://example.test", max_tokens=8)
            with self.assertRaisesRegex(ValueError, "token budget"):
                await publisher.publish_batch([Image("not-even-read.png") for _ in range(10)])
            service.register_file.assert_not_called()
            self.assertEqual(publisher.owned, {})

    async def test_card_batch_total_size_preflight_does_not_publish_partial_urls(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "source.png"
            source.write_bytes(b"x" * 700)
            service = types.SimpleNamespace(handle_file=lambda token: None, register_file=AsyncMock())
            publisher = transport.ImagePublisher(service, Path(folder) / "cache", "https://example.test", max_image_bytes=1024, max_cache_bytes=1024)
            with self.assertRaisesRegex(ValueError, "cache budget"):
                await publisher.publish_batch([Image(str(source)), Image(str(source))])
            service.register_file.assert_not_called()

    async def test_size_limit_checked_before_image_decode_or_copy(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "big.png"
            source.write_bytes(b"x" * 2048)
            service = types.SimpleNamespace(handle_file=lambda token: None)
            publisher = transport.ImagePublisher(service, Path(folder) / "cache", "https://example.test", max_image_bytes=1024)
            with patch.object(transport.PILImage, "open", side_effect=AssertionError("must check size first")):
                with self.assertRaisesRegex(ValueError, "size limit"):
                    await publisher.publish(Image(str(source)))

    async def test_cache_capacity_revokes_evicted_image_tokens(self):
        with tempfile.TemporaryDirectory() as folder:
            service = types.SimpleNamespace(handle_file=lambda token: None)
            publisher = transport.ImagePublisher(service, folder, "https://example.test", max_image_bytes=1024, max_cache_bytes=1024)
            old = Path(folder) / (("a" * 64) + ".png")
            old.write_bytes(b"x" * 700)
            publisher.owned["old-token"] = (old, float("inf"))
            publisher._reserve_space(700)
            self.assertFalse(old.exists())
            self.assertNotIn("old-token", publisher.owned)

    async def test_own_tokens_reusable_other_tokens_oneshot_and_terminate_revokes(self):
        class Service:
            def __init__(self): self.tokens, self.counter = {}, 0
            async def register_file(self, path, timeout=None):
                self.counter += 1
                self.tokens[str(self.counter)] = path
                return str(self.counter)
            async def handle_file(self, token): return self.tokens.pop(token)
        from PIL import Image as PILImage
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "source.png"
            PILImage.new("RGB", (12, 8)).save(source)
            service = Service()
            external = await service.register_file("external")
            publisher = transport.ImagePublisher(service, Path(folder) / "cache", "https://example.test", ttl=60)
            publisher.install()
            url, width, height = await publisher.publish(Image(str(source)))
            token = url.rsplit("/", 1)[-1]
            self.assertNotIn(token, service.tokens)
            path = await service.handle_file(token)
            self.assertEqual(await service.handle_file(token), path)
            self.assertTrue(path.endswith(".png"))
            self.assertEqual((width, height), (12, 8))
            self.assertEqual(await service.handle_file(external), "external")
            with self.assertRaises(KeyError): await service.handle_file(external)
            publisher.close()
            with self.assertRaises(KeyError): await service.handle_file(token)

    async def test_expired_owned_token_unavailable(self):
        service = types.SimpleNamespace(handle_file=lambda token: None)
        with tempfile.TemporaryDirectory() as folder:
            publisher = transport.ImagePublisher(service, folder, "https://example.test", ttl=60)
            publisher.install()
            publisher.owned["expired"] = (Path(folder) / "image.png", 0)
            with self.assertRaises(FileNotFoundError): await service.handle_file("expired")
            publisher.close()


if __name__ == "__main__": unittest.main()
