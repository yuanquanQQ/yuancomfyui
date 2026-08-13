import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock
from urllib import error as urllib_error
from urllib import request as urllib_request

import server
from runninghub_client.browser import BrowserRunner
from runninghub_client.workflow_specs import (
    CompletionSpec,
    OutputSpec,
    UploadSpec,
    WorkflowSpec,
)


class FakeFuture:
    def __init__(self):
        self.callback = None

    def add_done_callback(self, callback):
        self.callback = callback


class ImmediateFuture:
    def __init__(self, result):
        self._result = result

    def result(self):
        return self._result


class SchedulerTests(unittest.TestCase):
    def setUp(self):
        self.original = (
            server.PROFILES,
            server.APP_ROOT,
            server.QUEUE_TIMEOUT_SECONDS,
            server.MAX_TASK_REQUEUES,
        )
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        server.PROFILES = root / "profiles"
        server.APP_ROOT = root
        server.PROFILES.mkdir()
        with server._tasks_lock:
            server._tasks.clear()
            server._task_queue.clear()
            server._account_busy.clear()
        with server._login_lock:
            server._login_processes.clear()

    def tearDown(self):
        with server._tasks_lock:
            server._tasks.clear()
            server._task_queue.clear()
            server._account_busy.clear()
        server.PROFILES, server.APP_ROOT, server.QUEUE_TIMEOUT_SECONDS, server.MAX_TASK_REQUEUES = self.original
        self.temp_dir.cleanup()

    def add_account(self, account):
        profile = server.PROFILES / account
        profile.mkdir()
        (profile / "config.json").write_text(
            json.dumps({"phone": account, "workflow_id": "123456"}),
            encoding="utf-8",
        )
        (profile / "state.json").write_text(
            json.dumps({
                "cookies": [{
                    "name": "Rh-Accesstoken",
                    "value": "token",
                    "expires": time.time() + 3600,
                }],
            }),
            encoding="utf-8",
        )

    def add_task(self, task_id):
        now = time.time()
        server._tasks[task_id] = {
            "task_id": task_id,
            "status": "queued",
            "requested_account": "auto",
            "created_at": now,
            "video_path": "video.mp4",
            "model_path": "model.png",
            "clothing_path": None,
        }
        server._task_queue.append(task_id)

    def test_two_accounts_receive_different_tasks(self):
        self.add_account("account_a")
        self.add_account("account_b")
        self.add_task("task_a")
        self.add_task("task_b")
        futures = []

        def submit(*_args):
            future = FakeFuture()
            futures.append(future)
            return future

        with mock.patch.object(server._executor, "submit", side_effect=submit):
            server._dispatch_tasks()

        self.assertEqual(2, len(futures))
        accounts = {server._tasks["task_a"]["account"], server._tasks["task_b"]["account"]}
        self.assertEqual({"account_a", "account_b"}, accounts)
        self.assertEqual(accounts, server._account_busy)

    def test_failed_task_releases_account_and_dispatches_next(self):
        self.add_account("account_a")
        self.add_task("task_a")
        self.add_task("task_b")
        submitted = []

        def submit(*_args):
            future = FakeFuture()
            submitted.append(future)
            return future

        with mock.patch.object(server._executor, "submit", side_effect=submit):
            server._dispatch_tasks()
            self.assertEqual("running", server._tasks["task_a"]["status"])
            server._finish_task(
                "task_a",
                "account_a",
                ImmediateFuture({"status": "failed", "error": "download failed"}),
            )

        self.assertEqual("failed", server._tasks["task_a"]["status"])
        self.assertEqual("running", server._tasks["task_b"]["status"])
        self.assertEqual({"account_a"}, server._account_busy)
        self.assertEqual(2, len(submitted))

    def test_timeout_task_is_requeued_up_to_limit(self):
        """Timed-out tasks are re-queued, then permanently failed after limit."""
        self.add_account("account_a")
        task_id = "task_timeout_test"
        now = time.time()
        server._tasks[task_id] = {
            "task_id": task_id,
            "status": "queued",
            "requested_account": "auto",
            "created_at": now,
            "video_path": "video.mp4",
            "model_path": "model.png",
            "clothing_path": None,
            "workflow_id": "123456",
            "video": "video.mp4",
            "model": "model.png",
            "clothing": None,
            "retry_count": 0,
        }
        server._task_queue.append(task_id)
        server.MAX_TASK_REQUEUES = 2

        # Dispatch — picks up the task
        submitted = []

        def submit(*_args):
            future = FakeFuture()
            submitted.append(future)
            return future

        with mock.patch.object(server._executor, "submit", side_effect=submit):
            server._dispatch_tasks()
            self.assertEqual("running", server._tasks[task_id]["status"])
            # Simulate timeout
            server._finish_task(
                task_id,
                "account_a",
                ImmediateFuture({
                    "status": "failed",
                    "error": "任务运行超时（3000 秒），未检测到完成弹窗",
                }),
            )

        # Original task should be failed
        self.assertEqual("failed", server._tasks[task_id]["status"])
        # A re-queued task should have been created (may already be running
        # if _dispatch_tasks picked it up immediately)
        requeued = [
            t for t in server._tasks.values()
            if t.get("original_task_id") == task_id
        ]
        self.assertEqual(1, len(requeued))
        self.assertIn(requeued[0]["status"], ("queued", "running"))
        self.assertEqual(1, requeued[0]["retry_count"])

    def test_queue_timeout_marks_task_failed(self):
        self.add_task("task_a")
        server.QUEUE_TIMEOUT_SECONDS = 1
        server._tasks["task_a"]["created_at"] = time.time() - 2

        server._dispatch_tasks()

        task = server._tasks["task_a"]
        self.assertEqual("failed", task["status"])
        self.assertEqual("排队超时", task["stage_detail"])
        self.assertNotIn("task_a", server._task_queue)


class BrowserUploadTests(unittest.TestCase):
    def test_workflow_spec_resolves_fallback_and_optional_inputs(self):
        spec = WorkflowSpec(
            name="test",
            uploads=(
                UploadSpec("source", "1", "upload", "源图", "image"),
                UploadSpec(
                    "mask", "2", "upload", "遮罩", "image",
                    fallback_key="source",
                ),
                UploadSpec(
                    "reference", "3", "upload", "参考图", "image",
                    required=False,
                ),
            ),
            outputs=(OutputSpec("9", ("save image",), "image"),),
            completion=CompletionSpec(minimum_run_seconds=0),
        )

        resolved = spec.resolve_uploads({"source": "source.png"})

        self.assertEqual(
            [("source", "source.png"), ("mask", "source.png")],
            [(upload.key, path) for upload, path in resolved],
        )

    def test_upload_inputs_uses_declared_nodes_and_widgets(self):
        spec = WorkflowSpec(
            name="image",
            uploads=(UploadSpec("photo", "42", "pick file", "照片", "image"),),
            outputs=(OutputSpec("99", ("save image",), "image"),),
        )
        runner = BrowserRunner.__new__(BrowserRunner)
        runner.workflow_spec = spec
        runner._report_progress = mock.Mock()
        runner._upload_one = mock.Mock()

        runner.upload_inputs({"photo": "photo.png"})

        args = runner._upload_one.call_args.args
        kwargs = runner._upload_one.call_args.kwargs
        self.assertEqual(("42", "pick file"), args[:2])
        self.assertTrue(args[2].endswith("photo.png"))
        self.assertEqual("image", kwargs["file_widget"])

    def test_context_menu_uses_configured_save_action(self):
        spec = WorkflowSpec(
            name="image",
            uploads=(),
            outputs=(OutputSpec("99", ("save image",), "image"),),
        )
        runner = BrowserRunner.__new__(BrowserRunner)
        runner.workflow_spec = spec
        runner._dismiss_popups = mock.Mock()
        runner._dismiss_rife_popup = mock.Mock()
        runner._page = mock.MagicMock()
        runner._comfy = mock.Mock()
        runner._comfy.evaluate.return_value = {
            "state": "not_found", "available": ["Save Preview"]
        }

        with tempfile.TemporaryDirectory() as directory:
            saved = runner._download_via_context_menu(Path(directory))

        self.assertEqual([], saved)
        evaluate_args = runner._comfy.evaluate.call_args.args
        self.assertIn("saveimage", evaluate_args[1])
        self.assertIn("99", evaluate_args[0])

    def test_upload_response_may_be_filename_string(self):
        """Upload API returning a bare JSON string should not crash."""
        runner = BrowserRunner.__new__(BrowserRunner)
        runner._page = mock.Mock()
        runner._comfy = mock.Mock()
        response = mock.Mock()
        response.status = 200
        response.text.return_value = '"uploaded.png"'
        response.json.return_value = "uploaded.png"
        runner._page.request.post.return_value = response
        runner._comfy.evaluate.return_value = {"ok": True}

        with tempfile.TemporaryDirectory() as directory:
            file_path = Path(directory) / "source.png"
            file_path.write_bytes(b"png")
            runner._upload_via_fetch_and_callback(
                "1116", "upload", "image", str(file_path),
            )

        script = runner._comfy.evaluate.call_args.args[0]
        self.assertIn("uploaded.png", script)


class LoginSessionTests(unittest.TestCase):
    def test_pointer_moves_are_coalesced_without_losing_boundaries(self):
        session = server._new_login_session("account")

        server._queue_login_event_locked(session, {"type": "down"})
        server._queue_login_event_locked(
            session, {"type": "move", "x": 0.1, "y": 0.5})
        server._queue_login_event_locked(
            session, {"type": "move", "x": 0.8, "y": 0.5})
        server._queue_login_event_locked(session, {"type": "up"})

        self.assertEqual(
            ["down", "move", "up"],
            [event["type"] for event in session["events"]],
        )
        self.assertEqual(0.8, session["events"][1]["x"])

    def test_leaving_slider_stage_clears_frame_atomically(self):
        session = server._new_login_session("account")
        session["stage"] = "slider"
        session["frame"] = b"private slider frame"

        server._set_login_status_locked(
            session, "code_required", "enter SMS code")

        self.assertEqual("code_required", session["stage"])
        self.assertIsNone(session["frame"])

    def test_session_id_rejects_stale_login_session(self):
        account = "account"
        current = server._new_login_session(account)
        stale = server._new_login_session(account)
        with server._login_lock:
            server._login_sessions[account] = current
            self.assertIs(
                current,
                server._current_login_session_locked(
                    account, current["session_id"]),
            )
            self.assertIsNone(
                server._current_login_session_locked(
                    account, stale["session_id"]),
            )
            server._login_sessions.pop(account, None)

    def test_http_view_stops_returning_frame_after_slider(self):
        account = "http_test_account"
        session = server._new_login_session(account)
        png = b"\x89PNG\r\n\x1a\nmock-frame"
        with server._login_lock:
            server._login_sessions[account] = session
        httpd = server.http.server.ThreadingHTTPServer(
            ("127.0.0.1", 0), server.Handler)
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        base = f"http://127.0.0.1:{httpd.server_address[1]}"
        query = f"?session_id={session['session_id']}"
        headers = {"X-Login-Token": session["token"]}
        try:
            frame_request = urllib_request.Request(
                base + "/api/internal/login/frame" + query,
                data=png,
                headers={**headers, "Content-Type": "image/png"},
                method="POST",
            )
            urllib_request.urlopen(frame_request, timeout=2).read()
            status_request = urllib_request.Request(
                base + "/api/internal/login/status" + query,
                data=json.dumps({
                    "stage": "slider", "detail": "slider ready",
                }).encode(),
                headers={**headers, "Content-Type": "application/json"},
                method="POST",
            )
            urllib_request.urlopen(status_request, timeout=2).read()
            view_url = (
                base + "/api/accounts/login/view?account=" + account
                + "&session_id=" + session["session_id"]
            )
            self.assertEqual(png, urllib_request.urlopen(view_url, timeout=2).read())

            done_request = urllib_request.Request(
                base + "/api/internal/login/status" + query,
                data=json.dumps({
                    "stage": "code_required", "detail": "enter code",
                }).encode(),
                headers={**headers, "Content-Type": "application/json"},
                method="POST",
            )
            urllib_request.urlopen(done_request, timeout=2).read()
            try:
                response = urllib_request.urlopen(view_url, timeout=2)
            except urllib_error.HTTPError as exc:
                self.fail(f"Expected 204, got {exc.code}")
            self.assertEqual(204, response.status)
            self.assertEqual(b"", response.read())
        finally:
            httpd.shutdown()
            httpd.server_close()
            thread.join(timeout=2)
            with server._login_lock:
                server._login_sessions.pop(account, None)


if __name__ == "__main__":
    unittest.main()
