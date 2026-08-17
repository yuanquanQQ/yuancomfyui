from contextlib import contextmanager
from pathlib import Path
import tempfile

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

    def evaluate(self, script, argument):
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


def test_single_preview_uses_existing_download_path():
    runner = BrowserRunner()
    runner._page = FakePage()
    runner._comfy = FakeComfy(1)
    output = OutputSpec(node_id="83", media_type="image")

    assert runner._download_preview_batch(
        Path(".runtime"), output, ["savepreview"]
    ) is None
    assert runner._comfy.saved_indexes == []
