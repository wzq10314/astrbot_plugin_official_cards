"""Withdraw only a confirmed menu predecessor, with every network boundary fake."""
import importlib
import types
import unittest
from unittest.mock import AsyncMock, Mock, patch

import test_transport as fixtures
import test_keyboard_pages as pagination


receipts = importlib.import_module("astrbot_plugin_official_cards.menu_receipts")
pages = pagination.pages
transport = fixtures.transport


class ReceiptAPI:
    """Record submission and confirmation separately so deletion order is visible."""

    def __init__(self, trace, outcomes=()):
        self.trace, self.calls, self.outcomes = trace, [], list(outcomes)
        self.on_post = None

    async def _post(self, scene, payload):
        self.calls.append(payload)
        self.trace.append(("send", scene, len(self.calls)))
        if self.on_post:
            self.on_post()
        result = self.outcomes.pop(0) if self.outcomes else {"id": f"receipt-{len(self.calls)}"}
        if isinstance(result, BaseException):
            raise result
        if isinstance(result, dict) and result.get("id"):
            self.trace.append(("receipt", result["id"]))
        return result

    async def post_group_message(self, **payload):
        return await self._post("group", payload)

    async def post_c2c_message(self, **payload):
        return await self._post("c2c", payload)

    async def post_message(self, **payload):
        return await self._post("channel", payload)


def event_for(chain=None, api=None, *, scene="group", destination=None, **owner):
    owner.setdefault("session", "group-openid" if scene == "group" else "friend-openid")
    event = pagination.Event(chain, api, **owner)
    target = owner["session"] if destination is None else destination
    if scene == "group":
        source = fixtures.GroupMessage()
        source.group_openid = target
    elif scene == "c2c":
        source = fixtures.C2CMessage()
        source.author = types.SimpleNamespace(user_openid=target)
    else:
        source = fixtures.Message()
        source.channel_id = target
    event.message_obj.raw_message = source
    return event


class MenuReceiptTransportTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.trace, self.now = [], [100.0]
        self.cards = transport.CardTransport(fixtures.Publisher())
        self.cards.keyboard_pages = pages.KeyboardPageStore(clock=lambda: self.now[0])
        self.cards.menu_receipts = receipts.MenuReceiptStore(clock=lambda: self.now[0])
        self.delete = AsyncMock(side_effect=self._record_delete)
        self.cards.menu_receipts._delete = self.delete
        self.log = Mock()
        # The existing platform fixture supplies only logger.info.
        self.receipt_logger = patch.object(receipts, "logger", self.log)
        self.transport_logger = patch.object(transport, "logger", self.log)
        self.receipt_logger.start()
        self.transport_logger.start()
        self.addCleanup(self.receipt_logger.stop)
        self.addCleanup(self.transport_logger.stop)
        self.cards.install()
        self.addCleanup(self.cards.close)
        # Image generation is a separate contract; all cards here contain text.
        self.cards.render_help = AsyncMock(return_value=None)

    async def _record_delete(self, api, scene, target, message_id):
        self.trace.append(("delete", scene, target, message_id))
        return True

    async def first_menu(self, api=None, **event_options):
        api = api or ReceiptAPI(self.trace)
        chain = fixtures.Chain([fixtures.Plain("分页测试内容")])
        chain.qqofficial_buttons = pagination.dynamic_buttons(25)
        event = event_for(chain, api, **event_options)
        previous_tokens = set(self.cards.keyboard_pages.entries)
        await event._post_send_one(chain.derive(chain.chain))
        token, = set(self.cards.keyboard_pages.entries) - previous_tokens
        return event, token

    async def next_event(self, token, api, number=2, **event_options):
        event = event_for(api=api, **event_options)
        plugin = types.SimpleNamespace(transport=self.cards)
        results = [result async for result in pagination.page_handler()(plugin, event, token, number)]
        self.assertEqual(len(results), 1)
        event.send_buffer = results[0]
        return event

    async def send_page(self, event):
        chain = event.send_buffer
        return await event._post_send_one(chain.derive(chain.chain))

    def stored(self, event, token):
        return self.cards.menu_receipts.entries[(pages.event_owner(event), token)]

    async def assert_replaces_only_after_confirmation(self, scene):
        original, token = await self.first_menu(scene=scene)
        self.delete.assert_not_awaited()
        self.assertEqual(self.stored(original, token).message_id, "receipt-1")
        replacement = await self.next_event(token, original.bot.api, scene=scene)
        await self.send_page(replacement)
        target = "group-openid" if scene == "group" else "friend-openid"
        self.assertEqual(self.trace, [
            ("send", scene, 1), ("receipt", "receipt-1"),
            ("send", scene, 2), ("receipt", "receipt-2"),
            ("delete", scene, target, "receipt-1"),
        ])
        self.assertEqual(self.stored(original, token).message_id, "receipt-2")
        self.assertEqual(self.stored(original, token).page, 2)
        self.assertTrue(replacement.marked_sent)
        self.assertEqual(len(original.bot.api.calls), 2)
        destination = "group_openid" if scene == "group" else "openid"
        self.assertEqual(original.bot.api.calls[-1][destination], target)
        self.assertIn("keyboard", original.bot.api.calls[-1])
        self.assertNotEqual(self.delete.call_args.args[-1], replacement.message_obj.message_id)

    async def test_group_page_confirmed_before_previous_menu_is_deleted(self):
        await self.assert_replaces_only_after_confirmation("group")

    async def test_c2c_page_confirmed_before_previous_menu_is_deleted(self):
        await self.assert_replaces_only_after_confirmation("c2c")

    async def test_send_timeout_keeps_old_receipt_without_retry(self):
        original, token = await self.first_menu()
        original.bot.api.outcomes.append(TimeoutError("uncertain delivery"))
        replacement = await self.next_event(token, original.bot.api)
        with self.assertRaises(TimeoutError):
            await self.send_page(replacement)
        self.delete.assert_not_awaited()
        self.assertEqual(self.stored(original, token).message_id, "receipt-1")
        self.assertEqual(len(original.bot.api.calls), 2)
        self.assertFalse(replacement.marked_sent)
        self.assertIsNone(replacement.get_extra(receipts.MENU_RECEIPT_HINT_KEY))

    async def test_missing_or_failed_send_receipt_keeps_old_menu(self):
        for missing in (None, {}, {"id": "failed-id", "code": 100},
                        {"id": "failed-id", "status": "failed"}):
            with self.subTest(response=missing):
                api = ReceiptAPI(self.trace, [{"id": "old-menu"}, missing])
                original, token = await self.first_menu(api)
                replacement = await self.next_event(token, api)
                with self.assertRaisesRegex(RuntimeError, "delivery is unconfirmed"):
                    await self.send_page(replacement)
                self.delete.assert_not_awaited()
                self.assertEqual(self.stored(original, token).message_id, "old-menu")
                self.assertEqual(len(api.calls), 2)
                self.assertFalse(replacement.marked_sent)

    async def assert_ordinary_reply_preserves_menu(self, text, command):
        original, token = await self.first_menu()
        chain = fixtures.Chain([fixtures.Plain(text)])
        chain.qqofficial_buttons = [{"label": "返回帮助", "command": "/功能菜单", "enter": True}]
        event = event_for(chain, original.bot.api)
        event.get_message_str = lambda: command
        await event._post_send_one(chain)
        self.delete.assert_not_awaited()
        self.assertEqual(self.stored(original, token).message_id, "receipt-1")
        self.assertEqual(len(self.cards.menu_receipts.entries), 1)
        self.assertTrue(event.marked_sent)

    async def test_ordinary_query_reply_does_not_recall_menu(self):
        await self.assert_ordinary_reply_preserves_menu("查询结果：当前状态正常。", "/查询状态")

    async def test_button_usage_reply_does_not_recall_menu(self):
        await self.assert_ordinary_reply_preserves_menu("用法：/切换账号 <序号>", "/按钮输入 issued-token")

    async def test_keyboard_rejection_fallback_does_not_recall_old_menu(self):
        original, token = await self.first_menu()
        api = original.bot.api
        api.outcomes.extend([fixtures.ServerError("not allowed custom keyboard"), {"id": "text-fallback"}])
        replacement = await self.next_event(token, api)
        await self.send_page(replacement)
        self.assertEqual(len(api.calls), 3)
        self.assertIn("keyboard", api.calls[1])
        self.assertNotIn("keyboard", api.calls[2])
        self.delete.assert_not_awaited()
        self.assertEqual(self.stored(original, token).message_id, "receipt-1")
        self.assertTrue(replacement.marked_sent)
        self.assertIsNone(replacement.get_extra(receipts.MENU_RECEIPT_HINT_KEY))

    async def test_menu_at_115_seconds_is_not_recalled(self):
        original, token = await self.first_menu()
        self.now[0] += 115.0
        replacement = await self.next_event(token, original.bot.api)
        await self.send_page(replacement)
        self.delete.assert_not_awaited()
        self.assertEqual(self.stored(original, token).message_id, "receipt-2")
        self.assertTrue(replacement.marked_sent)

    async def test_menu_just_before_115_seconds_can_be_recalled(self):
        original, token = await self.first_menu()
        self.now[0] += 114.999
        replacement = await self.next_event(token, original.bot.api)
        await self.send_page(replacement)
        self.delete.assert_awaited_once()
        self.assertEqual(self.delete.call_args.args[-1], "receipt-1")

    async def test_other_owner_or_scene_cannot_recall_original_menu(self):
        original, token = await self.first_menu()
        for owner in ({"sender": "bob"}, {"platform": "other-platform"},
                      {"session": "other-group"}, {"admin": True},
                      {"scene": "c2c", "session": "group-openid"}):
            with self.subTest(owner=owner):
                replacement = await self.next_event(token, original.bot.api, **owner)
                self.assertIsNone(replacement.get_extra(pages.PAGE_HINT_KEY))
                await self.send_page(replacement)
                self.delete.assert_not_awaited()
                self.assertEqual(self.stored(original, token).message_id, "receipt-1")
        self.assertEqual(len(self.cards.menu_receipts.entries), 1)

    async def test_actual_destination_must_match_owner_session(self):
        for scene in ("group", "c2c"):
            with self.subTest(scene=scene):
                original, token = await self.first_menu(scene=scene)
                old_id = self.stored(original, token).message_id
                replacement = await self.next_event(token, original.bot.api, scene=scene,
                                                    destination="different-destination")
                await self.send_page(replacement)
                self.delete.assert_not_awaited()
                self.assertEqual(self.stored(original, token).message_id, old_id)

    async def test_separate_menu_tokens_keep_separate_latest_receipts(self):
        original, first_token = await self.first_menu()
        second, second_token = await self.first_menu(original.bot.api)
        self.assertNotEqual(first_token, second_token)
        self.delete.assert_not_awaited()
        self.assertEqual(self.stored(original, first_token).message_id, "receipt-1")
        self.assertEqual(self.stored(second, second_token).message_id, "receipt-2")
        replacement = await self.next_event(first_token, original.bot.api)
        await self.send_page(replacement)
        self.delete.assert_awaited_once()
        self.assertEqual(self.delete.call_args.args[-1], "receipt-1")
        self.assertEqual(self.stored(original, first_token).message_id, "receipt-3")
        self.assertEqual(self.stored(second, second_token).message_id, "receipt-2")

    async def test_equal_receipt_never_deletes_itself(self):
        api = ReceiptAPI(self.trace, [{"id": "same-id"}, {"id": "same-id"}])
        original, token = await self.first_menu(api)
        await self.send_page(await self.next_event(token, api))
        self.delete.assert_not_awaited()
        self.assertEqual(self.stored(original, token).message_id, "same-id")
        self.assertEqual(self.stored(original, token).page, 2)

    async def test_delete_exception_keeps_new_page_without_duplicate_post(self):
        original, token = await self.first_menu()
        self.delete.side_effect = OSError("withdrawal unavailable")
        replacement = await self.next_event(token, original.bot.api)
        await self.send_page(replacement)
        self.delete.assert_awaited_once()
        self.assertEqual(len(original.bot.api.calls), 2)
        self.assertEqual(self.stored(original, token).message_id, "receipt-2")
        self.assertTrue(replacement.marked_sent)
        self.log.warning.assert_called_once()

    async def test_delete_rejection_keeps_new_page_without_duplicate_post(self):
        original, token = await self.first_menu()
        self.delete.side_effect = None
        self.delete.return_value = False
        replacement = await self.next_event(token, original.bot.api)
        await self.send_page(replacement)
        self.delete.assert_awaited_once()
        self.assertEqual(len(original.bot.api.calls), 2)
        self.assertEqual(self.stored(original, token).message_id, "receipt-2")
        self.assertTrue(replacement.marked_sent)

    async def test_multiple_next_pages_delete_only_each_confirmed_predecessor(self):
        original, token = await self.first_menu()
        for number in (2, 3, 4, 1):
            await self.send_page(await self.next_event(token, original.bot.api, number))
        deleted = [call.args[-1] for call in self.delete.await_args_list]
        self.assertEqual(deleted, ["receipt-1", "receipt-2", "receipt-3", "receipt-4"])
        self.assertEqual(self.stored(original, token).message_id, "receipt-5")
        self.assertEqual(self.stored(original, token).page, 1)
        self.assertEqual(len(original.bot.api.calls), 5)
        self.assertNotIn("receipt-5", deleted)
        self.assertNotIn(original.message_obj.message_id, deleted)

    async def test_receipt_hint_is_consumed_before_post_and_cleared_on_reused_event(self):
        original, token = await self.first_menu()
        replacement = await self.next_event(token, original.bot.api)
        original.bot.api.on_post = lambda: self.assertIsNone(
            replacement.get_extra(receipts.MENU_RECEIPT_HINT_KEY))
        await self.send_page(replacement)
        self.assertIsNone(replacement.get_extra(receipts.MENU_RECEIPT_HINT_KEY))
        self.delete.assert_awaited_once()
        replacement.set_extra(pages.PAGE_HINT_KEY, None)
        # Simulate another producer leaving an old hint on the same event.
        replacement.set_extra(receipts.MENU_RECEIPT_HINT_KEY, (token, 2))
        ordinary = fixtures.Chain([fixtures.Plain("查询结果")])
        ordinary.qqofficial_buttons = [dict(pages.HOME_BUTTON)]
        replacement.send_buffer = ordinary
        await replacement._post_send_one(ordinary)
        self.delete.assert_awaited_once()
        self.assertEqual(self.stored(original, token).message_id, "receipt-2")
        self.assertIsNone(replacement.get_extra(receipts.MENU_RECEIPT_HINT_KEY))


class MenuReceiptStoreTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.now = [100.0]
        self.store = receipts.MenuReceiptStore(clock=lambda: self.now[0])
        self.store._delete = AsyncMock(return_value=True)
        self.event = event_for()
        self.logger_patch = patch.object(receipts, "logger", Mock())
        self.logger_patch.start()
        self.addCleanup(self.logger_patch.stop)

    async def test_invalid_receipts_do_not_replace_a_confirmed_receipt(self):
        await self.store.complete(self.event, "menu", 1, {"id": "old-menu"}, 100.0)
        invalid = (None, {}, {"id": ""}, {"id": "   "}, {"id": 123},
                   {"id": "x" * 2049}, {"id": "failed", "code": 1},
                   {"id": "failed", "retcode": "1"}, {"id": "failed", "errcode": 1},
                   {"id": "failed", "status": "failed"})
        for response in invalid:
            with self.subTest(response=repr(response)[:70]):
                await self.store.complete(self.event, "menu", 2, response, 100.0)
                self.assertEqual(self.store.entries[(pages.event_owner(self.event), "menu")].message_id,
                                 "old-menu")
                self.store._delete.assert_not_awaited()

    async def test_response_object_and_message_id_receipts_replace_in_sequence(self):
        await self.store.complete(self.event, "menu", 1, types.SimpleNamespace(id="object-id"), 100.0)
        await self.store.complete(self.event, "menu", 2, {"message_id": "dict-id", "code": "0"}, 100.0)
        self.store._delete.assert_awaited_once_with(self.event.bot.api, "group", "group-openid", "object-id")
        self.assertEqual(self.store.entries[(pages.event_owner(self.event), "menu")].message_id, "dict-id")

    async def test_unverified_owner_or_unsupported_scene_never_records_receipt(self):
        for event in (event_for(sender=""), event_for(session=""),
                      event_for(platform=""), event_for(scene="channel")):
            with self.subTest(owner=pages.event_owner(event)):
                await self.store.complete(event, "menu", 1, {"id": "sent-menu"}, 100.0)
        self.assertFalse(self.store.entries)
        self.store._delete.assert_not_awaited()

    async def test_future_submission_time_never_replaces_a_confirmed_receipt(self):
        await self.store.complete(self.event, "menu", 1, {"id": "old-menu"}, 100.0)
        await self.store.complete(self.event, "menu", 2, {"id": "new-menu"}, 101.0)
        self.assertEqual(self.store.entries[(pages.event_owner(self.event), "menu")].message_id, "old-menu")
        self.store._delete.assert_not_awaited()


class ResponseContext:
    def __init__(self, response):
        self.response = response

    async def __aenter__(self):
        return self.response

    async def __aexit__(self, *args):
        return False


def fake_http(status=204, raw=b"", *, sandbox=False):
    content = types.SimpleNamespace(read=AsyncMock(return_value=raw))
    response = types.SimpleNamespace(status=status, content=content)
    session = types.SimpleNamespace(request=Mock(return_value=ResponseContext(response)))
    http = types.SimpleNamespace(check_session=AsyncMock(), is_sandbox=sandbox,
                                 _session=session, _headers={"Authorization": "Bot fake-credential"})
    return types.SimpleNamespace(_http=http), response


class MenuDeleteContractTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.store = receipts.MenuReceiptStore()
        self.log = Mock()
        self.logger_patch = patch.object(receipts, "logger", self.log)
        self.logger_patch.start()
        self.addCleanup(self.logger_patch.stop)

    async def test_group_and_c2c_routes_encode_ids_in_production_and_sandbox(self):
        for scene, collection in (("group", "groups"), ("c2c", "users")):
            for sandbox, host in ((False, "api.bot.qq.com"), (True, "sandbox.api.sgroup.qq.com")):
                with self.subTest(scene=scene, sandbox=sandbox):
                    api, response = fake_http(sandbox=sandbox)
                    ok = await self.store._delete(api, scene, "target/id 雪", "sent/id?# 雪")
                    self.assertTrue(ok)
                    api._http.check_session.assert_awaited_once()
                    api._http._session.request.assert_called_once()
                    args, kwargs = api._http._session.request.call_args
                    self.assertEqual(args, ("DELETE", f"https://{host}/v2/{collection}/"
                                           "target%2Fid%20%E9%9B%AA/messages/sent%2Fid%3F%23%20%E9%9B%AA"))
                    self.assertIs(kwargs["headers"], api._http._headers)
                    self.assertEqual(kwargs["timeout"].total, 5)
                    self.assertIs(kwargs["allow_redirects"], False)
                    response.content.read.assert_awaited_once_with(4097)

    async def test_empty_or_zero_code_success_bodies_are_accepted(self):
        for status, raw in ((200, b""), (204, b""), (200, b"{}"),
                            (200, b'{"code":0}'), (200, b'{"code":"0"}'),
                            (200, b'{"retcode":0}'), (200, b'{"errcode":0}')):
            with self.subTest(status=status, raw=raw):
                api, response = fake_http(status, raw)
                self.assertTrue(await self.store._delete(api, "group", "target", "old-menu"))
                api._http._session.request.assert_called_once()
                response.content.read.assert_awaited_once_with(4097)

    async def test_redirect_or_failure_status_is_rejected_without_retry(self):
        for status in (201, 202, 301, 302, 307, 308, 400, 403, 404, 429, 500):
            with self.subTest(status=status):
                api, _ = fake_http(status)
                self.assertFalse(await self.store._delete(api, "group", "target", "old-menu"))
                api._http._session.request.assert_called_once()
                self.assertIs(api._http._session.request.call_args.kwargs["allow_redirects"], False)

    async def test_nonzero_code_or_invalid_body_is_rejected_without_retry(self):
        for raw in (b'{"code":1}', b'{"code":"100"}', b'{"retcode":1}',
                    b'{"errcode":1}', b'{"code":"unknown"}', b"<html>error</html>",
                    b"[]", b"null", b"false", b"\xff", b"x" * 4097):
            with self.subTest(raw=raw[:70]):
                api, response = fake_http(200, raw)
                self.assertFalse(await self.store._delete(api, "c2c", "target", "old-menu"))
                api._http._session.request.assert_called_once()
                response.content.read.assert_awaited_once_with(4097)

    async def test_rejection_logs_do_not_expose_credentials_ids_or_body(self):
        api, _ = fake_http(403, b'{"code":"secret-code","detail":"secret-body"}')
        self.assertFalse(await self.store._delete(api, "group", "secret-target", "secret-message"))
        message = self.log.warning.call_args.args[0]
        self.assertIn("HTTP 403", message)
        for private in ("secret-code", "secret-body", "secret-target", "secret-message", "fake-credential"):
            self.assertNotIn(private, message)

    async def test_unsupported_scene_or_missing_http_does_not_issue_request(self):
        api, _ = fake_http()
        self.assertFalse(await self.store._delete(api, "channel", "target", "old-menu"))
        api._http.check_session.assert_not_awaited()
        api._http._session.request.assert_not_called()
        self.assertFalse(await self.store._delete(types.SimpleNamespace(), "group", "target", "old-menu"))


if __name__ == "__main__":
    unittest.main()
