import tempfile
import unittest
from pathlib import Path
from unittest import mock

from runninghub_client.browser import BrowserRunner


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
