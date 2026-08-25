import tempfile
import unittest
from pathlib import Path
from unittest import mock

from runninghub_client.browser import BrowserRunner
from runninghub_client.workflow_specs import (
    OutputSpec,
    NodeModeSpec,
    TextInputSpec,
    UploadSpec,
    WidgetInputSpec,
    WorkflowSpec,
)


class BrowserPostTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.runner = BrowserRunner(
            post_id="2087936157744189442",
            user_data_dir=Path(self.temp_dir.name),
        )
        self.page = mock.MagicMock()
        self.button = mock.MagicMock()
        self.page.get_by_text.return_value.last = self.button
        self.page.locator.return_value.inner_text.return_value = "Post content"
        self.context = mock.MagicMock()
        self.context.pages = [self.page]
        self.runner._page = self.page
        self.runner._context = self.context
        self.runner._dismiss_rife_popup = mock.MagicMock(return_value=False)
        self.runner._dismiss_popups = mock.MagicMock()
        self.runner._find_comfy_frame = mock.MagicMock(return_value="comfy-frame")

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_post_mode_opens_post_clicks_run_and_finds_workflow(self):
        self.page.url = "https://www.runninghub.cn/post/2087936157744189442"
        self.button.click.side_effect = lambda **_kwargs: setattr(
            self.page, "url", "https://www.runninghub.cn/workflow/current"
        )
        self.runner._open_post_workflow()

        self.page.goto.assert_called_once_with(
            "https://www.runninghub.cn/post/2087936157744189442",
            wait_until="domcontentloaded",
            timeout=60000,
        )
        self.page.get_by_text.assert_called_once_with("运行工作流", exact=True)
        self.button.wait_for.assert_called_once_with(state="visible", timeout=30000)
        self.button.click.assert_called_once_with(timeout=15000)
        self.runner._find_comfy_frame.assert_called_once_with()
        self.assertEqual("comfy-frame", self.runner._comfy)

    def test_post_mode_retries_after_overlay_blocks_first_navigation(self):
        self.page.url = "https://www.runninghub.cn/post/2087936157744189442"
        attempts = 0

        def click(**_kwargs):
            nonlocal attempts
            attempts += 1
            if attempts == 2:
                self.page.url = "https://www.runninghub.cn/workflow/current"

        self.button.click.side_effect = click
        self.runner._open_post_workflow()

        self.assertEqual(2, self.button.click.call_count)
        self.assertEqual(2, self.runner._dismiss_popups.call_count)
        self.runner._find_comfy_frame.assert_called_once_with()

    def test_post_mode_reloads_post_after_click_retries_do_not_navigate(self):
        self.page.url = "https://www.runninghub.cn/post/2087936157744189442"
        navigation_count = 0

        def goto(*_args, **_kwargs):
            nonlocal navigation_count
            navigation_count += 1
            self.page.url = "https://www.runninghub.cn/post/2087936157744189442"

        def click(**_kwargs):
            if navigation_count == 2:
                self.page.url = "https://www.runninghub.cn/workflow/current"

        self.page.goto.side_effect = goto
        self.button.click.side_effect = click

        self.runner._open_post_workflow()

        self.assertEqual(2, self.page.goto.call_count)
        self.assertEqual(3, self.button.click.call_count)
        self.runner._find_comfy_frame.assert_called_once_with()

    def test_post_mode_keeps_left_page_when_click_also_opens_right_page(self):
        self.page.url = "https://www.runninghub.cn/post/2087936157744189442"
        right_page = mock.MagicMock()
        right_page.url = "https://www.runninghub.cn/workflow/duplicate"

        def click(**_kwargs):
            self.page.url = "https://www.runninghub.cn/workflow/actual"
            self.context.pages = [self.page, right_page]

        self.button.click.side_effect = click
        self.runner._open_post_workflow()

        self.assertIs(self.runner._page, self.page)
        right_page.wait_for_load_state.assert_not_called()

    def test_post_mode_selects_first_left_workflow_page(self):
        self.page.url = "https://www.runninghub.cn/post/2087936157744189442"
        left_page = mock.MagicMock()
        left_page.url = "https://www.runninghub.cn/workflow/actual"
        right_page = mock.MagicMock()
        right_page.url = "https://www.runninghub.cn/workflow/duplicate"

        def click(**_kwargs):
            self.context.pages = [self.page, left_page, right_page]

        self.button.click.side_effect = click
        self.runner._open_post_workflow()

        self.assertIs(self.runner._page, left_page)
        right_page.wait_for_load_state.assert_not_called()

    def test_post_mode_reports_expired_login_instead_of_waiting_for_iframe(self):
        self.button.wait_for.side_effect = TimeoutError("button missing")
        self.page.locator.return_value.inner_text.return_value = "验证码登录"

        with self.assertRaisesRegex(RuntimeError, "登录状态已失效"):
            self.runner._open_post_workflow()
        self.runner._find_comfy_frame.assert_not_called()

    def test_legacy_workflow_id_urls_remain_supported(self):
        runner = BrowserRunner(
            workflow_id="123456",
            user_data_dir=Path(self.temp_dir.name),
        )
        self.assertIn(
            "https://www.runninghub.cn/workflow/123456",
            runner._candidate_workflow_urls(),
        )

    def test_task_list_state_uses_newest_visible_status(self):
        self.page.evaluate.return_value = {
            "state": "running", "text": "生成中 00:08", "top": 120,
        }

        result = self.runner._current_task_list_state()

        self.assertEqual("running", result["state"])
        script = self.page.evaluate.call_args.args[0]
        self.assertIn("matches.sort", script)
        self.assertIn("任务失败", script)

    def test_task_list_state_returns_none_when_sidebar_has_no_status(self):
        self.page.evaluate.return_value = None

        self.assertIsNone(self.runner._current_task_list_state())

    def test_output_media_fingerprints_are_scoped_to_configured_outputs(self):
        self.runner.workflow_spec = WorkflowSpec(
            name="outputs",
            uploads=(),
            outputs=(OutputSpec("149", media_type="image"),),
        )
        comfy = mock.MagicMock()
        comfy.evaluate.return_value = {"149": ["https://example/output.png"]}
        self.runner._comfy = comfy

        result = self.runner._output_media_fingerprints()

        self.assertEqual({"149": ["https://example/output.png"]}, result)
        self.assertEqual(["149"], comfy.evaluate.call_args.args[1])

    def test_boolean_widget_is_set_on_configured_node(self):
        self.runner.workflow_spec = WorkflowSpec(
            name="person_replace",
            uploads=(),
            outputs=(OutputSpec("119", media_type="video"),),
            widgets=(WidgetInputSpec(
                "upload_background", "250", "RGTHREE_TOGGLE_AND_NAV",
                "上传替换背景", True, False, True, True, "rgthree_toggle",
            ),),
        )
        comfy = mock.MagicMock()
        comfy.evaluate.return_value = {
            "state": "updated", "previous": True, "current": False,
        }
        self.runner._comfy = comfy

        self.runner.set_widget_inputs({"upload_background": False})

        payload = comfy.evaluate.call_args.args[1]
        self.assertEqual("250", payload["nodeId"])
        self.assertEqual("RGTHREE_TOGGLE_AND_NAV", payload["widgetName"])
        self.assertFalse(payload["desired"])

    def test_matching_rgthree_toggle_is_not_clicked(self):
        self.runner.workflow_spec = WorkflowSpec(
            name="person_replace", uploads=(),
            outputs=(OutputSpec("119", media_type="video"),),
            widgets=(WidgetInputSpec(
                "upload_background", "250", "RGTHREE_TOGGLE_AND_NAV",
                "上传替换背景", True, False, True, True, "rgthree_toggle",
            ),),
        )
        comfy = mock.MagicMock()
        comfy.evaluate.return_value = {"state": "unchanged", "current": True}
        self.runner._comfy = comfy

        self.runner.set_widget_inputs({"upload_background": True})

        self.assertTrue(comfy.evaluate.call_args.args[1]["desired"])

    def test_fixed_node_mode_is_applied_without_canvas_clicking(self):
        self.runner.workflow_spec = WorkflowSpec(
            name="scail_multi_reference",
            uploads=(),
            outputs=(OutputSpec("161", media_type="video"),),
            node_modes=(NodeModeSpec("1336", 2, "参考图节点 1336"),),
        )
        comfy = mock.MagicMock()
        comfy.evaluate.return_value = {
            "state": "updated", "previous": 0, "mode": 2,
        }
        self.runner._comfy = comfy

        self.runner.set_node_modes()

        self.assertEqual(
            {"nodeId": "1336", "mode": 2},
            comfy.evaluate.call_args.args[1],
        )

    def test_new_output_media_ignores_preexisting_preview(self):
        baseline = {"149": ["old.png"]}

        self.assertFalse(self.runner._has_new_output_media(
            baseline, {"149": ["old.png"]},
        ))
        self.assertTrue(self.runner._has_new_output_media(
            baseline, {"149": ["old.png", "new.png"]},
        ))

    def test_visible_error_dialog_prefers_iframe_error_text(self):
        comfy = mock.MagicMock()
        comfy.evaluate.return_value = "Your API balance is insufficient"
        self.runner._comfy = comfy

        text = self.runner._visible_error_dialog_text()

        self.assertEqual("Your API balance is insufficient", text)
        self.page.evaluate.assert_not_called()

    def test_cancel_request_clicks_runninghub_sidebar_before_stopping(self):
        self.page.evaluate.side_effect = [
            {
                "clicked": True,
                "text": "取消",
                "cardText": "Animate 动作迁移 生成中 00:32 取消",
            },
            {"clicked": True, "text": "确认取消"},
        ]
        self.runner.request_cancel()

        with self.assertRaisesRegex(RuntimeError, "任务已取消"):
            self.runner._raise_if_cancelled()

        self.assertEqual(2, self.page.evaluate.call_count)
        self.assertEqual(2, self.page.wait_for_timeout.call_count)
        self.assertTrue(self.runner._cloud_cancel_result["clicked"])
        self.assertEqual(
            "确认取消",
            self.runner._cloud_cancel_result["confirmation"]["text"],
        )

    def test_cancel_request_tolerates_missing_cloud_cancel_button(self):
        self.page.evaluate.return_value = {
            "clicked": False,
            "reason": "active_cancel_not_found",
        }
        self.runner.request_cancel()

        with self.assertRaisesRegex(RuntimeError, "任务已取消"):
            self.runner._raise_if_cancelled()

        self.page.evaluate.assert_called_once()
        self.assertEqual(
            "active_cancel_not_found",
            self.runner._cloud_cancel_result["reason"],
        )

    def test_popup_cancel_watcher_covers_page_and_iframe(self):
        self.runner._dismiss_popups = BrowserRunner._dismiss_popups.__get__(
            self.runner, BrowserRunner
        )
        self.runner._comfy = mock.MagicMock()
        self.page.evaluate.return_value = {"clicked": 1, "watching": True}
        self.runner._comfy.evaluate.return_value = {
            "clicked": 2, "watching": True,
        }

        clicked = self.runner._dismiss_cancel_popups()

        self.assertEqual(3, clicked)
        self.page.evaluate.assert_called_once()
        self.runner._comfy.evaluate.assert_called_once()
        script = self.page.evaluate.call_args.args[0]
        self.assertIn("/^(取消|Cancel)$/i", script)
        self.assertIn("button.closest(popupSelector)", script)
        self.assertIn("setInterval(scan, 250)", script)

    def test_generic_popup_dismissal_no_longer_clicks_global_cancel(self):
        self.runner._dismiss_popups = BrowserRunner._dismiss_popups.__get__(
            self.runner, BrowserRunner
        )
        self.runner._dismiss_cancel_popups = mock.MagicMock(return_value=0)
        self.runner._comfy = None

        self.runner._dismiss_popups()

        selectors = [call.args[0] for call in self.page.locator.call_args_list]
        self.assertNotIn('button:has-text("取消")', selectors)
        self.assertNotIn('button:has-text("Cancel")', selectors)

    def test_stale_show_report_popup_is_dismissed_before_setup(self):
        self.runner._dismiss_comfy_popups = mock.MagicMock()
        self.runner._visible_completion_popup = mock.MagicMock(
            return_value={"scope": "main page", "text": "Show Report"}
        )

        self.runner._dismiss_stale_completion_popup()

        self.assertEqual(2, self.runner._dismiss_comfy_popups.call_count)
        self.assertEqual(2, self.runner._dismiss_popups.call_count)
        self.assertEqual(2, self.page.wait_for_timeout.call_count)

    def test_setup_does_not_repeat_dismissal_without_stale_report(self):
        self.runner._dismiss_comfy_popups = mock.MagicMock()
        self.runner._visible_completion_popup = mock.MagicMock(return_value=None)

        self.runner._dismiss_stale_completion_popup()

        self.runner._dismiss_comfy_popups.assert_called_once_with()
        self.runner._dismiss_popups.assert_called_once_with()
        self.page.wait_for_timeout.assert_called_once_with(500)

    def test_workflow_target_nodes_include_inputs_texts_and_outputs_once(self):
        self.runner.workflow_spec = WorkflowSpec(
            name="adaptive",
            uploads=(
                UploadSpec("source", "105", "upload", "source"),
                UploadSpec("mask", "105", "upload", "mask"),
            ),
            texts=(TextInputSpec("prompt", "120", "text", "prompt"),),
            outputs=(OutputSpec("149", media_type="image"),),
        )

        node_ids = self.runner._workflow_target_node_ids({
            "source": "source.png",
            "mask": "mask.png",
            "prompt": "detail",
        })

        self.assertEqual(["105", "120", "149"], node_ids)

    def test_canvas_auto_fit_verifies_every_configured_node_is_visible(self):
        comfy = mock.MagicMock()
        comfy.evaluate.side_effect = [
            {
                "ok": True,
                "nodeIds": ["105", "149"],
                "missing": [],
                "scale": 0.18,
            },
            {
                "visibleNodeIds": ["105", "149"],
                "nonClickableNodeIds": [],
                "nodes": [
                    {"nodeId": "105", "clickable": True},
                    {"nodeId": "149", "clickable": True},
                ],
            },
        ]
        self.runner._comfy = comfy

        result = self.runner._fit_nodes_on_canvas(["105", "149"])

        self.assertEqual(0.18, result["scale"])
        comfy.wait_for_timeout.assert_called_once_with(1000)
        self.assertEqual(
            ["105", "149"],
            comfy.evaluate.call_args_list[0].args[1]["nodeIds"],
        )
        fit_script = comfy.evaluate.call_args_list[0].args[0]
        verification_script = comfy.evaluate.call_args_list[1].args[0]
        self.assertIn("reservedGraphWidth", fit_script)
        self.assertIn("canvasWidth - rightReserve", fit_script)
        self.assertIn("rightSafeBoundary", verification_script)
        self.assertIn("node_outside_left_safe_area", verification_script)
        self.assertIn("diagnostics.push('small_on_screen')", verification_script)
        self.assertNotIn("reasons.push('too_small_to_click')", verification_script)
        self.assertNotIn("reasons.push('canvas_point_blocked')", verification_script)
        self.assertEqual(1, result["attempts"])

    def test_canvas_auto_fit_stops_before_upload_when_node_is_not_visible(self):
        comfy = mock.MagicMock()
        fit_result = {
            "ok": True,
            "nodeIds": ["105", "149"],
            "missing": [],
            "scale": 0.18,
        }
        failed_verification = {
            "visibleNodeIds": ["105"],
            "nonClickableNodeIds": ["149"],
            "nodes": [
                {"nodeId": "105", "clickable": True},
                {"nodeId": "149", "clickable": False,
                 "reasons": ["center_outside_safe_area"]},
            ],
        }
        comfy.evaluate.side_effect = [
            fit_result, failed_verification,
            fit_result, failed_verification,
        ]
        self.runner._comfy = comfy

        with self.assertRaisesRegex(RuntimeError, "149"):
            self.runner._fit_nodes_on_canvas(
                ["105", "149"], max_attempts=2
            )

    def test_canvas_auto_fit_retries_until_all_nodes_are_clickable(self):
        comfy = mock.MagicMock()
        fit_result = {
            "ok": True,
            "nodeIds": ["105", "149"],
            "missing": [],
            "scale": 0.15,
        }
        comfy.evaluate.side_effect = [
            fit_result,
            {
                "nonClickableNodeIds": ["149"],
                "nodes": [{"nodeId": "149", "clickable": False}],
            },
            fit_result,
            {
                "nonClickableNodeIds": [],
                "nodes": [
                    {"nodeId": "105", "clickable": True},
                    {"nodeId": "149", "clickable": True},
                ],
            },
        ]
        self.runner._comfy = comfy

        result = self.runner._fit_nodes_on_canvas(
            ["105", "149"], max_attempts=3
        )

        self.assertEqual(2, result["attempts"])
        self.assertEqual(4, comfy.evaluate.call_count)

    def test_task_list_state_recognizes_runninghub_queue(self):
        self.page.evaluate.return_value = {
            "state": "queued", "text": "排队中（第164位）", "top": 120,
        }

        result = self.runner._current_task_list_state()

        self.assertEqual("queued", result["state"])
        script = self.page.evaluate.call_args.args[0]
        self.assertIn("排队中", script)

    def test_failed_task_waits_for_completion_grace_period(self):
        first_seen, confirmed = self.runner._observe_task_failure(
            {"state": "failed"}, None, 100,
        )
        self.assertEqual(100, first_seen)
        self.assertFalse(confirmed)

        first_seen, confirmed = self.runner._observe_task_failure(
            {"state": "failed"}, first_seen, 159,
        )
        self.assertFalse(confirmed)

        first_seen, confirmed = self.runner._observe_task_failure(
            {"state": "failed"}, first_seen, 160,
        )
        self.assertTrue(confirmed)

    def test_running_task_cancels_failure_observation(self):
        first_seen, confirmed = self.runner._observe_task_failure(
            {"state": "running"}, 100, 120,
        )
        self.assertIsNone(first_seen)
        self.assertFalse(confirmed)

    def test_queued_task_cancels_failure_observation(self):
        first_seen, confirmed = self.runner._observe_task_failure(
            {"state": "queued"}, 100, 120,
        )
        self.assertIsNone(first_seen)
        self.assertFalse(confirmed)


if __name__ == "__main__":
    unittest.main()
