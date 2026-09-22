"""One-click full regression test for the YunComfyUI workbench.

Submits one task per configured workflow to the running client
(http://127.0.0.1:8081) using materials from client/library/.
Double-click full_test.bat (or run `python full_test.py`) to trigger.

Edit TEST_PLAN / SKIP_WORKFLOWS below to change coverage.

Text/number/switch fields are intentionally omitted where the server-side
catalog default is the desired value.
"""

import sys
from pathlib import Path

import requests

CLIENT_ROOT = Path(__file__).resolve().parent
PORT_RANGE = range(8081, 8091)

# Workflows deliberately not covered by the regression run.
SKIP_WORKFLOWS = {"ootd_7day", "minimax_h3_dual_stage", "person_replace"}

IMG = "library/images/"
VID = "library/videos/"
AUD = "library/audio/"

# key -> server-relative input paths (verified against client/library)
TEST_PLAN = {
    "person_replace": {
        "background": IMG + "398798bebe59646337fc37e45447458d.png",
        "video": VID + "9fe541d4e8b00644c317cbc82c7783f8.mp4",
        "model": IMG + "2a214fc4ac9efd6538b5779d6e18c62c.jpg",
    },
    "animate_transfer": {
        "motion_video": VID + "9fe541d4e8b00644c317cbc82c7783f8.mp4",
        "reference_image": IMG + "2a214fc4ac9efd6538b5779d6e18c62c.jpg",
        "motion_strength": "0.2",
        "frame_load_cap": "900",
    },
    "ltx23_hd_digital_human": {
        "portrait": IMG + "398798bebe59646337fc37e45447458d.png",
        "audio": AUD + "M500001ziKgJ3o5Ipp.mp3",
    },
    "qwen_prompt_image": {
        "reference": IMG + "2a214fc4ac9efd6538b5779d6e18c62c.jpg",
    },
    "hd_restore_detail_v2": {
        "source": IMG + "b6435ac4134efcbea70c4acac2f09009.jpg",
    },
    "scail_multi_reference": {
        "motion_video": VID + "9fe541d4e8b00644c317cbc82c7783f8.mp4",
        "reference1": IMG + "b6435ac4134efcbea70c4acac2f09009.jpg",
        "reference2": IMG + "2a214fc4ac9efd6538b5779d6e18c62c.jpg",
    },
    "scail_seven_outfit": {
        "motion_video": VID + "b.mp4",
        "outfit1": IMG + "b6435ac4134efcbea70c4acac2f09009.jpg",
        "outfit2": IMG + "398798bebe59646337fc37e45447458d.png",
        "outfit3": IMG + "2a214fc4ac9efd6538b5779d6e18c62c.jpg",
        "outfit4": IMG + "8dfa6bcb96c972d9e7362051b93d2873.jpg",
        "outfit5": IMG + "398798bebe59646337fc37e45447458d.png",
        "outfit6": IMG + "2a214fc4ac9efd6538b5779d6e18c62c.jpg",
        "outfit7": IMG + "b6435ac4134efcbea70c4acac2f09009.jpg",
    },
    "scail_4k_pose_background": {
        "background": IMG + "2a214fc4ac9efd6538b5779d6e18c62c.jpg",
        "person": IMG + "b6435ac4134efcbea70c4acac2f09009.jpg",
    },
    "krea2_realistic_4k": {},
    "qwen_multi_view": {
        "character": IMG + "8dfa6bcb96c972d9e7362051b93d2873.jpg",
    },
    "auto_storyboard_short_video": {
        "reference": IMG + "8dfa6bcb96c972d9e7362051b93d2873.jpg",
    },
    "firered_ecommerce_tryon": {
        "person": IMG + "398798bebe59646337fc37e45447458d.png",
        "garment": IMG + "2a214fc4ac9efd6538b5779d6e18c62c.jpg",
    },
    "minimax_h3_four_view": {
        "character": IMG + "b6435ac4134efcbea70c4acac2f09009.jpg",
    },
    "seedvr2_upscale": {
        "source": IMG + "b6435ac4134efcbea70c4acac2f09009.jpg",
    },
}


def find_base_url():
    for port in PORT_RANGE:
        url = f"http://127.0.0.1:{port}"
        try:
            resp = requests.get(f"{url}/api/license/status", timeout=2)
            if not resp.ok:
                continue
            body = resp.json()
            if body.get("active"):
                return url
            # Freshly started servers answer from a cold cache; force the
            # online check once before giving up on this port.
            checked = requests.post(f"{url}/api/license/check", json={}, timeout=30)
            if checked.ok and checked.json().get("active"):
                return url
        except Exception:
            continue
    raise SystemExit("[full_test] 未找到已激活的工作台服务（端口 8081-8090），请先启动客户端")


def check_materials():
    missing = []
    for wf, inputs in TEST_PLAN.items():
        for key, value in inputs.items():
            text = str(value)
            if text.startswith("library/") or text.startswith("data/") \
                    or text.startswith("uploads/"):
                if not (CLIENT_ROOT / text).is_file():
                    missing.append(f"{wf}.{key}: {text}")
    if missing:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        raise SystemExit("[full_test] 素材缺失：\n  " + "\n  ".join(missing))


def ready_accounts(base):
    accounts = requests.get(f"{base}/api/accounts", timeout=10).json()
    return [a["id"] for a in accounts if a.get("ready") and a["id"] != "default"]


def coveraged_workflows(base):
    try:
        catalog = requests.get(f"{base}/api/workflows", timeout=15).json()
    except Exception:
        return None
    return {w["key"] for w in catalog}


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    base = find_base_url()
    check_materials()
    accounts = ready_accounts(base)
    if not accounts:
        raise SystemExit("[full_test] 没有已登录就绪的账号，请先在工作台完成登录后再试")
    catalog = coveraged_workflows(base)
    if catalog is not None:
        unknown = sorted(set(TEST_PLAN) - catalog)
        if unknown:
            print(f"[full_test] 注意：计划中的工作流已不在目录中: {unknown}")
        uncovered = sorted(catalog - set(TEST_PLAN) - SKIP_WORKFLOWS)
        if uncovered:
            print(f"[full_test] 注意：目录中未被测试计划覆盖: {uncovered}")

    print(f"[full_test] 服务 {base}；可用账号 {accounts}")
    ok, failed = 0, 0
    for workflow, inputs in TEST_PLAN.items():
        if workflow in SKIP_WORKFLOWS:
            print(f"  [跳过] {workflow}")
            continue
        payload = {"workflow": workflow, **inputs}
        resp = requests.post(f"{base}/api/run", json=payload, timeout=20)
        try:
            body = resp.json()
        except ValueError:
            body = {"error": resp.text[:200]}
        if resp.status_code == 200 and body.get("task_id"):
            ok += 1
            print(f"  [入队] {workflow:<28} -> {body['task_id']}")
        else:
            failed += 1
            print(f"  [失败] {workflow:<28} -> HTTP {resp.status_code} "
                  f"{body.get('error') or body}")
    print(f"[full_test] 提交完成：入队 {ok}，失败 {failed}。"
          "进度请查看工作台界面（结果保存到 works/ 目录）。")
    return 0 if failed == 0 and ok > 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
