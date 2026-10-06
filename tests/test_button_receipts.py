"""Every button recalls its confirmed source, without sharing another user's menu."""
import asyncio
import importlib
import types
import unittest
from unittest.mock import AsyncMock, Mock, patch

import test_transport as fixtures
import test_keyboard_pages as pagination
import test_menu_receipts as predecessor
import test_menu_routes as route_fixtures
import test_interactions as interaction_fixtures


receipts = importlib.import_module("astrbot_plugin_official_cards.button_receipts")
routes = route_fixtures.routes
transport = fixtures.transport
CLICKED = receipts.CLICKED_CARD_KEY
OUTGOING = receipts.OUTGOING_BUTTONS_KEY


def token(number=1):
    return "oc:" + str(number).zfill(24)


def event_for(chain=None, api=None, **kwargs):
    return predecessor.event_for(chain, api, **kwargs)


class ButtonReceiptStoreTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.now = [100.0]
        self.store = receipts.ButtonReceiptStore(clock=lambda: self.now[0])
        self.store._delete = AsyncMock(return_value=True)
        self.event = event_for()
        self.logger_patch = patch.object(receipts, "logger", Mock())
        self.logger_patch.start()
        self.addCleanup(self.logger_patch.stop)

    def bind(self, event=None, response=None, tokens=None, submitted_at=None):
        event = event or self.event
        self.store.bind(event, (token(),) if tokens is None else tokens,
                        {"id": "old-card"} if response is None else response,
                        self.now[0] if submitted_at is None else submitted_at)
        return event

    def click(self, *, source=None, **kwargs):
        event = event_for(**kwargs)
        event.set_extra(CLICKED, token() if source is None else source)
        return event

    async def test_group_owner_recalls_only_its_confirmed_source(self):
        self.bind()
        clicked = self.click()
        self.assertTrue(self.store.has_clicked_source(clicked))
        await self.store.after_reply(clicked, {"id": "new-result"})
        self.store._delete.assert_awaited_once_with(clicked.bot.api, "group", "group-openid", "old-card")
        self.assertNotEqual(self.store._delete.call_args.args[-1], clicked.message_obj.message_id)

    async def test_private_owner_uses_private_target(self):
        original = event_for(scene="c2c", session="alice", sender="alice")
        self.bind(original)
        clicked = self.click(scene="c2c", session="alice", sender="alice")
        await self.store.after_reply(clicked, {"id": "new-result"})
        self.store._delete.assert_awaited_once_with(clicked.bot.api, "c2c", "alice", "old-card")

    async def test_other_user_does_not_consume_original_owners_recall(self):
        self.bind()
        await self.store.after_reply(self.click(sender="bob"), {"id": "bobs-result"})
        self.store._delete.assert_not_awaited()
        await self.store.after_reply(self.click(), {"id": "alices-result"})
        self.store._delete.assert_awaited_once()

    async def test_other_platform_group_and_scene_cannot_recall(self):
        self.bind()
        for kwargs in ({"platform": "other-platform"}, {"session": "other-group"},
                       {"scene": "c2c", "session": "group-openid"},
                       {"destination": "wrong-actual-target"}):
            with self.subTest(scope=kwargs):
                await self.store.after_reply(self.click(**kwargs), {"id": "new-result"})
                self.store._delete.assert_not_awaited()
        await self.store.after_reply(self.click(), {"id": "valid-result"})
        self.store._delete.assert_awaited_once()

    async def test_unknown_or_user_supplied_message_id_is_not_a_source(self):
        self.bind()
        for value in (None, "old-card", "user-message", token(999), {"message_id": "old-card"}):
            with self.subTest(source=value):
                event = self.click(source=value)
                if value is None:
                    event.set_extra(CLICKED, None)
                self.assertFalse(self.store.has_clicked_source(event))
                await self.store.after_reply(event, {"id": "new-result"})
        self.store._delete.assert_not_awaited()

    async def test_no_receipt_or_failed_response_keeps_source_available(self):
        self.bind()
        event = self.click()
        for response in (None, {}, {"id": ""}, {"id": "   "},
                         {"id": "bad", "status": "failed"}, {"id": "bad", "code": 1},
                         {"id": "bad", "retcode": "1"}, {"id": "bad", "errcode": 1}):
            with self.subTest(response=response):
                await self.store.after_reply(event, response)
                self.store._delete.assert_not_awaited()
        await self.store.after_reply(event, {"message_id": "confirmed-result", "code": "0"})
        self.store._delete.assert_awaited_once()

    async def test_invalid_binding_never_records_unconfirmed_source(self):
        invalid = (None, {}, {"id": ""}, {"id": " "}, {"id": "failed", "code": 1},
                   {"id": "failed", "status": "failed"}, {"id": "x" * 2049})
        for response in invalid:
            with self.subTest(response=repr(response)[:70]):
                self.store.bind(self.event, (token(),), response, self.now[0])
                self.assertFalse(self.store.has_clicked_source(self.click()))
        self.store._delete.assert_not_awaited()

    async def test_unsupported_or_actual_destination_mismatch_never_binds(self):
        for kwargs in ({"scene": "channel"}, {"destination": "wrong-destination"},
                       {"platform": ""}, {"session": ""}, {"sender": ""}):
            with self.subTest(owner=kwargs):
                self.store.bind(event_for(**kwargs), (token(),), {"id": "old-card"}, self.now[0])
                self.assertFalse(self.store.has_clicked_source(self.click(**kwargs)))
        self.store._delete.assert_not_awaited()

    async def test_future_submission_and_expired_sources_are_not_deleted(self):
        self.bind(submitted_at=101.0)
        await self.store.after_reply(self.click(), {"id": "new-result"})
        self.store._delete.assert_not_awaited()
        self.bind()
        self.now[0] += 115.0
        await self.store.after_reply(self.click(), {"id": "new-result"})
        self.store._delete.assert_not_awaited()

    async def test_just_before_deadline_can_be_recalled(self):
        self.bind()
        self.now[0] += 114.999
        await self.store.after_reply(self.click(), {"id": "new-result"})
        self.store._delete.assert_awaited_once()

    async def test_same_receipt_never_deletes_itself_or_consumes_source(self):
        self.bind()
        clicked = self.click()
        await self.store.after_reply(clicked, {"id": "old-card"})
        self.store._delete.assert_not_awaited()
        await self.store.after_reply(clicked, {"id": "new-result"})
        self.store._delete.assert_awaited_once()

    async def test_all_buttons_of_one_card_share_one_recall(self):
        self.bind(tokens=(token(1), token(2)))
        await self.store.after_reply(self.click(source=token(1)), {"id": "first-result"})
        await self.store.after_reply(self.click(source=token(2)), {"id": "second-result"})
        self.store._delete.assert_awaited_once()

    async def test_concurrent_replies_only_delete_source_once(self):
        self.bind(tokens=(token(1), token(2)))
        started, finish = asyncio.Event(), asyncio.Event()

        async def wait_delete(*args):
            started.set()
            await finish.wait()
            return True

        self.store._delete.side_effect = wait_delete
        first = asyncio.create_task(self.store.after_reply(self.click(source=token(1)), {"id": "result-1"}))
        await asyncio.wait_for(started.wait(), timeout=1)
        await self.store.after_reply(self.click(source=token(2)), {"id": "result-2"})
        self.store._delete.assert_awaited_once()
        finish.set()
        await first

    async def test_delete_failure_keeps_new_result_and_does_not_retry(self):
        self.bind()
        self.store._delete.side_effect = OSError("temporary delete failure")
        clicked = self.click()
        await self.store.after_reply(clicked, {"id": "new-result"})
        await self.store.after_reply(clicked, {"id": "second-result"})
        self.store._delete.assert_awaited_once()

    async def test_successful_plain_fallback_can_recall_without_markdown_receipt(self):
        self.bind()
        await self.store.after_reply(self.click(), None, confirmed_plain=True)
        self.store._delete.assert_awaited_once()

    async def test_manual_command_or_cleared_store_never_recalls(self):
        self.bind()
        await self.store.after_reply(event_for(), {"id": "manual-result"})
        self.store._delete.assert_not_awaited()
        self.store.clear()
        self.assertFalse(self.store.has_clicked_source(self.click()))
        await self.store.after_reply(self.click(), {"id": "new-result"})
        self.store._delete.assert_not_awaited()


class AllButtonTransportTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.now, self.trace, self.source_counter = [100.0], [], 0
        self.cards = transport.CardTransport(fixtures.Publisher())
        self.cards.callbacks_enabled = True
        self.cards.button_receipts = receipts.ButtonReceiptStore(clock=lambda: self.now[0])
        self.cards.menu_receipts.clock = lambda: self.now[0]
        self.delete = AsyncMock(side_effect=self._record_delete)
        self.cards.button_receipts._delete = self.delete
        self.log_patch = patch.object(transport, "logger", Mock())
        self.receipt_log_patch = patch.object(receipts, "logger", Mock())
        self.log_patch.start()
        self.receipt_log_patch.start()
        self.addCleanup(self.log_patch.stop)
        self.addCleanup(self.receipt_log_patch.stop)
        self.cards.render_help = AsyncMock(return_value=None)
        self.cards.install()
        self.addCleanup(self.cards.close)

    async def _record_delete(self, api, scene, target, message_id):
        self.trace.append(("delete", scene, target, message_id))
        return True

    async def first_card(self, *, buttons=None, scene="group"):
        api = predecessor.ReceiptAPI(self.trace)
        self.source_counter += 1
        if self.source_counter > 1:
            api.outcomes.append({"id": f"source-card-{self.source_counter}"})
        recalls_before = self.delete.await_count
        chain = fixtures.Chain([fixtures.Plain("功能卡片")])
        chain.qqofficial_buttons = buttons or [
            {"label": "王者帮助", "command": "#王者帮助", "enter": True},
            {"label": "查询战绩", "command": "#查询战绩", "enter": True},
            {"label": "搜索用法", "command": "/pica搜索", "enter": False},
        ]
        event = event_for(chain, api, scene=scene)
        await event._post_send_one(chain.derive(chain.chain))
        issued = [item["action"]["data"] for item in pagination.actions(api.calls[0]["keyboard"])]
        self.assertTrue(all(value.startswith("oc:") for value in issued))
        self.assertEqual(self.delete.await_count, recalls_before)
        return event, issued

    def clicked_event(self, original, clicked_token, text="查询结果：已完成。", *, buttons=None,
                      markdown=None, **kwargs):
        chain = fixtures.Chain([fixtures.Plain(text)], markdown)
        chain.qqofficial_buttons = buttons or [dict(pagination.pages.HOME_BUTTON)]
        event = event_for(chain, original.bot.api, **kwargs)
        event.set_extra(CLICKED, clicked_token)
        event.set_extra("qqofficial_interaction_event_id", "trusted-outer-click-event")
        return event

    async def send(self, event):
        return await event._post_send_one(event.send_buffer.derive(event.send_buffer.chain))

    async def test_query_from_small_keyboard_recalls_after_new_receipt(self):
        original, issued = await self.first_card()
        clicked = self.clicked_event(original, issued[1])
        await self.send(clicked)
        self.assertEqual(self.trace, [
            ("send", "group", 1), ("receipt", "receipt-1"),
            ("send", "group", 2), ("receipt", "receipt-2"),
            ("delete", "group", "group-openid", "receipt-1"),
        ])
        self.assertTrue(clicked.marked_sent)
        self.assertNotIn("msg_id", original.bot.api.calls[-1])

    async def test_category_switch_and_parameter_usage_both_recall_source(self):
        for index, text in ((0, "王者营地帮助"), (2, "搜索用法：/pica搜索 <关键词>")):
            with self.subTest(button=index):
                original, issued = await self.first_card()
                await self.send(self.clicked_event(original, issued[index], text))
        self.assertEqual(self.delete.await_count, 2)

    async def test_error_reply_is_a_delivered_result_and_recalls_source(self):
        original, issued = await self.first_card()
        clicked = self.clicked_event(original, issued[1], "查询失败：当前未绑定营地，请先绑定。")
        await self.send(clicked)
        self.delete.assert_awaited_once()

    async def test_progress_keeps_menu_until_actual_result_is_delivered(self):
        original, issued = await self.first_card()
        clicked = self.clicked_event(original, issued[1], "🔍 正在查询战绩，请稍候...")
        await self.send(clicked)
        self.delete.assert_not_awaited()
        self.assertTrue(self.cards.button_receipts.has_clicked_source(clicked))
        result = fixtures.Chain([fixtures.Plain("战绩结果：最近胜率 60%。")])
        result.qqofficial_buttons = [dict(pagination.pages.HOME_BUTTON)]
        clicked.send_buffer = result
        await self.send(clicked)
        self.delete.assert_awaited_once()
        self.assertEqual(self.delete.call_args.args[-1], "receipt-1")

    async def test_explicit_pending_card_is_preserved_until_final_reply(self):
        original, issued = await self.first_card()
        clicked = self.clicked_event(original, issued[1], "任务已进入处理队列。")
        clicked.send_buffer.qqofficial_pending = True
        await self.send(clicked)
        self.delete.assert_not_awaited()
        clicked.send_buffer = fixtures.Chain([fixtures.Plain("处理完成。")])
        await self.send(clicked)
        self.delete.assert_awaited_once()

    async def test_timeout_and_missing_receipt_preserve_source_for_retry(self):
        original, issued = await self.first_card()
        clicked = self.clicked_event(original, issued[1])
        original.bot.api.outcomes.append(TimeoutError("uncertain delivery"))
        with self.assertRaises(TimeoutError):
            await self.send(clicked)
        self.delete.assert_not_awaited()
        original.bot.api.outcomes.append({})
        with self.assertRaisesRegex(RuntimeError, "delivery is unconfirmed"):
            await self.send(clicked)
        self.delete.assert_not_awaited()
        await self.send(clicked)
        self.delete.assert_awaited_once()

    async def test_plain_fallback_success_recalls_but_failure_does_not(self):
        original, issued = await self.first_card()
        clicked = self.clicked_event(original, issued[1], markdown=False)
        with patch.object(self.cards, "_send_plain_session", AsyncMock(return_value=False)):
            await self.send(clicked)
        self.delete.assert_not_awaited()
        with patch.object(self.cards, "_send_plain_session", AsyncMock(side_effect=TimeoutError())):
            with self.assertRaises(TimeoutError):
                await self.send(clicked)
        self.delete.assert_not_awaited()
        with patch.object(self.cards, "_send_plain_session", AsyncMock(return_value=True)):
            await self.send(clicked)
        self.delete.assert_awaited_once()

    async def test_keyboard_rejection_final_reply_still_recalls_source(self):
        original, issued = await self.first_card()
        original.bot.api.outcomes.extend([
            fixtures.ServerError("not allowed custom keyboard"), {"id": "plain-final-receipt"},
        ])
        await self.send(self.clicked_event(original, issued[1]))
        self.delete.assert_awaited_once()
        self.assertNotIn("keyboard", original.bot.api.calls[-1])

    async def test_manual_query_keeps_previous_card(self):
        original, issued = await self.first_card()
        event = event_for(fixtures.Chain([fixtures.Plain("普通手动查询结果")]), original.bot.api)
        await self.send(event)
        self.delete.assert_not_awaited()

    async def test_different_actor_cannot_delete_original_card(self):
        original, issued = await self.first_card()
        for kwargs in ({"sender": "bob"}, {"platform": "other-platform"}, {"session": "other-group"}):
            with self.subTest(scope=kwargs):
                await self.send(self.clicked_event(original, issued[1], **kwargs))
                self.delete.assert_not_awaited()
        await self.send(self.clicked_event(original, issued[1]))
        self.delete.assert_awaited_once()

    async def test_new_card_source_is_bound_before_old_card_delete_wait(self):
        original, issued = await self.first_card()
        clicked = self.clicked_event(original, issued[0])

        async def inspect_new_source(*args):
            new_token = pagination.actions(original.bot.api.calls[-1]["keyboard"])[0]["action"]["data"]
            fresh = self.clicked_event(original, new_token)
            self.assertTrue(self.cards.button_receipts.has_clicked_source(fresh))
            return True

        self.delete.side_effect = inspect_new_source
        await self.send(clicked)
        self.delete.assert_awaited_once()

    async def test_multi_part_replies_do_not_recall_more_than_once(self):
        original, issued = await self.first_card()
        clicked = self.clicked_event(original, issued[1], "结果第一部分")
        await self.send(clicked)
        clicked.send_buffer = fixtures.Chain([fixtures.Plain("结果第二部分")])
        await self.send(clicked)
        self.delete.assert_awaited_once()


class ProgressDetectionTests(unittest.TestCase):
    def test_waiting_text_is_progress_but_final_errors_are_not(self):
        for text in ("🔍 正在查询战绩，请稍候...", "请稍等一下，正在查询～", "开始下载，请稍候"):
            with self.subTest(text=text):
                self.assertTrue(transport.is_progress_reply([fixtures.Plain(text)]))
        for text in ("查询失败，请稍后重试。", "解析超时，任务已停止。", "未完成：连接失败。",
                     "权限不足", "不支持此操作", "本次仅显示用法，未执行操作。", "已找到 3 条结果。"):
            with self.subTest(text=text):
                self.assertFalse(transport.is_progress_reply([fixtures.Plain(text)]))

    def test_image_result_with_waiting_caption_is_final(self):
        self.assertFalse(transport.is_progress_reply([
            fixtures.Plain("正在整理结果，请稍候"), fixtures.Image("returned-image.png")]))


class ButtonReceiptQueueTests(unittest.TestCase):
    def setUp(self):
        self.base = route_fixtures.MenuRouteTests()
        self.base.setUp()
        self.addCleanup(self.base.doCleanups)

    def test_help_requeue_copies_only_trusted_source_token(self):
        base = self.base
        base.event.set_extra(CLICKED, token())
        base.event.set_extra(OUTGOING, (token(3),))
        base.event.set_extra("private_credentials", {"password": "do-not-copy"})
        base.event.set_extra("qqofficial_interaction_event_id", "trusted-reply-event")
        self.assertTrue(routes.queue_original_help(base.context, base.event, "王者"))
        queued = base.adapter.events[0]
        self.assertEqual(queued.get_extra(CLICKED), token())
        self.assertEqual(queued.get_extra("qqofficial_interaction_event_id"), "trusted-reply-event")
        self.assertNotIn(OUTGOING, queued.extras)
        self.assertNotIn("private_credentials", queued.extras)


class ButtonReceiptInteractionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.base = interaction_fixtures.InteractionTests()
        await self.base.asyncSetUp()

    async def asyncTearDown(self):
        await self.base.asyncTearDown()
        self.base.doCleanups()

    async def test_only_authorized_callback_token_becomes_clicked_source(self):
        base = self.base
        callback = base.callback(data={"type": 11, "resolved": {
            "button_data": "oc:known", "message_id": "untrusted-user-message-id"}})
        await base.bridge.handle(base.adapter.client, callback)
        event = base.adapter.events[0]
        self.assertEqual(event.extra.get(CLICKED), "oc:known")
        self.assertNotIn("untrusted-user-message-id", str(event.extra))
        await base.bridge.handle(base.adapter.client, base.callback(
            id="another-user-click", group_member_openid="someone-else"))
        self.assertEqual(len(base.adapter.events), 1)


if __name__ == "__main__":
    unittest.main()
