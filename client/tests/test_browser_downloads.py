from contextlib import contextmanager
import base64
from pathlib import Path
import tempfile
from unittest import mock

from runninghub_client.browser import BrowserRunner
from runninghub_client.workflow_specs import OutputSpec


class FakeDownload:
    suggested_filename = "preview.png"

    def save_as(self, destination):
        Path(destination).write_bytes(b"image")


class FakeDownloadInfo:
    value = FakeDownload()


class FakePage:
    @contextmanager
    def expect_download(self, timeout):
        yield FakeDownloadInfo()

    def wait_for_timeout(self, milliseconds):
        return None


class FakeComfy:
    def __init__(self, image_count):
        self.image_count = image_count
        self.saved_indexes = []
        self.centered = False

    def wait_for_timeout(self, milliseconds):
        self.centered = True

    def evaluate(self, script, argument=None):
        if ("app.canvas.ds.offset" in script
                or "var ds=app.canvas.ds" in script):
            return {"ok": True}
        if isinstance(argument, str):
            return self.image_count
        self.saved_indexes.append(argument["imageIndex"])
        return {"state": "invoked", "label": "Save Preview"}


def test_preview_batch_downloads_every_image():
    runner = BrowserRunner()
    runner._page = FakePage()
    runner._comfy = FakeComfy(3)
    output = OutputSpec(
        node_id="448",
        menu_actions=("save preview",),
        media_type="image",
    )

    with tempfile.TemporaryDirectory(dir=".runtime") as directory:
        saved = runner._download_preview_batch(
            Path(directory), output, ["savepreview"]
        )

        assert runner._comfy.saved_indexes == [0, 1, 2]
        assert [Path(path).name for path in saved] == [
            "preview_01.png",
            "preview_02.png",
            "preview_03.png",
        ]
        assert all(Path(path).read_bytes() == b"image" for path in saved)


def test_single_preview_uses_image_sensitive_save_action():
    runner = BrowserRunner()
    runner._page = FakePage()
    runner._comfy = FakeComfy(1)
    output = OutputSpec(node_id="83", media_type="image")

    saved = runner._download_preview_batch(
        Path(".runtime"), output, ["savepreview"]
    )

    assert runner._comfy.saved_indexes == [0]
    assert len(saved) == 1
    Path(saved[0]).unlink()


def test_image_outputs_prefer_all_node_media_before_context_menu():
    runner = BrowserRunner()
    runner.workflow_spec = mock.Mock(
        outputs=(OutputSpec(node_id="114", media_type="image"),),
        strict_outputs=True,
    )
    runner._page = mock.Mock()
    runner._dismiss_comfy_popups = mock.Mock()
    runner._download_output_node_media = mock.Mock(
        return_value=["one.png", "two.png", "three.png"]
    )
    runner._download_via_context_menu = mock.Mock()

    with tempfile.TemporaryDirectory(dir=".runtime") as directory:
        saved = runner.download_outputs(directory)

    assert saved == ["one.png", "two.png", "three.png"]
    runner._download_via_context_menu.assert_not_called()


def test_output_node_media_can_save_rendered_private_image():
    runner = BrowserRunner()
    runner._page = FakePage()
    png = b"\x89PNG\r\n\x1a\n" + (b"x" * 12000)
    data_url = "data:image/png;base64," + base64.b64encode(png).decode()
    runner._comfy = mock.Mock()
    runner._comfy.evaluate.side_effect = [None, [data_url], []]
    output = OutputSpec(node_id="149", media_type="image")

    with tempfile.TemporaryDirectory(dir=".runtime") as directory:
        saved = runner._download_output_node_media(Path(directory), output)

        assert len(saved) == 1
        assert Path(saved[0]).read_bytes() == png
        assert runner._comfy.evaluate.call_count == 2
