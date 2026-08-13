"""
Full end-to-end test: 上传 → 运行 → 等待 → 下载
"""
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from runninghub_client.browser import BrowserRunner

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    stream=sys.stderr,
)

VIDEO_PATH = "data/video/d30fee59d6c58c8e51c10c65e91ec703.mp4"
MODEL_IMAGE_PATH = "data/pic/8baed76edd10056ba355fbe2bdacf963.png"
CLOTHING_IMAGE_PATH = "data/ple/398798bebe59646337fc37e45447458d.png"

def main():
    runner = BrowserRunner(
        slow_mo=200,
        workflow_id="2077757106073194497",
        user_data_dir="./profiles/13649856927",
    )

    print("=" * 60)
    print("E2E Test: 上传 → 运行 → 等待 → 下载")
    print("=" * 60)
    print(f"  视频: {VIDEO_PATH}")
    print(f"  模特: {MODEL_IMAGE_PATH}")
    print(f"  衣服: {CLOTHING_IMAGE_PATH}")
    print("")

    try:
        saved = runner.run(
            video_path=VIDEO_PATH,
            model_image_path=MODEL_IMAGE_PATH,
            clothing_image_path=CLOTHING_IMAGE_PATH,
            mode="plus",
            output_dir="./outputs",
            timeout=1200,
        )
        print(f"\nDownloaded files: {saved}")
        if saved:
            print("PASS: Full flow completed successfully!")
            sys.exit(0)
        else:
            print("FAIL: No files downloaded")
            sys.exit(1)
    except Exception as e:
        print(f"FAIL: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
