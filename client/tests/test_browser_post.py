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
        self.runner._find_comfy_frame = mock.MagicMock(return_value="comfy-frame")

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_post_mode_opens_post_clicks_run_and_finds_workflow(self):
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


if __name__ == "__main__":
    unittest.main()
