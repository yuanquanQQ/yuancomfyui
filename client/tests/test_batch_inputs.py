from pathlib import Path

import pytest

import server


def test_batch_inputs_pair_and_repeat_text_workflow():
    workflow = {
        "name": "文字工作流",
        "inputs": ({"key": "prompt", "input_type": "text"},),
    }
    groups = server._resolve_batch_workflow_inputs(
        workflow,
        {"inputs": {"prompt": ["first prompt", "second prompt"]}, "repeat": 2},
    )

    assert groups == [
        {"prompt": "first prompt"},
        {"prompt": "first prompt"},
        {"prompt": "second prompt"},
        {"prompt": "second prompt"},
    ]


def test_text_input_uses_server_default_when_omitted():
    workflow = {
        "name": "默认文字工作流",
        "inputs": ({
            "key": "prompt", "label": "提示词", "input_type": "text",
            "default": "原工作流提示词",
        },),
    }

    assert server._resolve_workflow_inputs(workflow, {}) == {
        "prompt": "原工作流提示词",
    }
    assert server._resolve_batch_workflow_inputs(
        workflow, {"inputs": {}},
    ) == [{"prompt": "原工作流提示词"}]


def test_textarea_renders_server_default_value():
    html = (
        Path(__file__).parents[1] / "static" / "index.html"
    ).read_text(encoding="utf-8")

    assert ">${escapeHtml(input.default??'')}</textarea>" in html


def test_numeric_inputs_use_defaults_and_validate_integer_values():
    workflow = {
        "name": "数值工作流",
        "inputs": (
            {
                "key": "strength", "label": "动作幅度",
                "input_type": "number", "default": 0.2, "min": 0,
            },
            {
                "key": "frames", "label": "加载帧数上限",
                "input_type": "integer", "default": 900, "min": 1,
            },
        ),
    }

    assert server._resolve_workflow_inputs(workflow, {}) == {
        "strength": 0.2, "frames": 900,
    }
    assert server._resolve_batch_workflow_inputs(
        workflow, {"inputs": {}},
    ) == [{"strength": 0.2, "frames": 900}]
    with pytest.raises(ValueError, match="必须是整数"):
        server._resolve_workflow_inputs(workflow, {"frames": 12.5})


def test_batch_inputs_cycle_shorter_file_input():
    workflow = {
        "name": "文件工作流",
        "inputs": (
            {"key": "background", "media_type": "image"},
            {"key": "model", "media_type": "image"},
            {"key": "video", "media_type": "video"},
        ),
    }
    model = "data/pic/8baed76edd10056ba355fbe2bdacf963.png"
    video = "data/video/d30fee59d6c58c8e51c10c65e91ec703.mp4"
    background = "data/pic/78203beb850680946d2172f8b3cd9b68.png"
    groups = server._resolve_batch_workflow_inputs(
        workflow,
        {
            "inputs": {
                "background": [background],
                "model": [model, model],
                "video": [video],
            }
        },
    )

    assert len(groups) == 2
    assert all(group["background"].endswith("78203beb850680946d2172f8b3cd9b68.png") for group in groups)
    assert all(group["video"].endswith("d30fee59d6c58c8e51c10c65e91ec703.mp4") for group in groups)


def person_replace_inputs():
    return (
        {"key": "upload_background", "label": "上传替换背景",
         "input_type": "boolean", "default": True},
        {"key": "background", "label": "替换背景图", "required": False,
         "required_when": {"key": "upload_background", "equals": True}},
        {"key": "model", "label": "人物参考图"},
    )


def test_optional_background_is_skipped_when_switch_is_off():
    model = "data/pic/8baed76edd10056ba355fbe2bdacf963.png"
    background = "data/pic/78203beb850680946d2172f8b3cd9b68.png"
    workflow = {"name": "人物替换", "inputs": person_replace_inputs()}

    single = server._resolve_workflow_inputs(
        workflow, {
            "upload_background": False, "background": background,
            "model": model,
        },
    )
    batch = server._resolve_batch_workflow_inputs(
        workflow,
        {"inputs": {
            "upload_background": [False], "background": [background],
            "model": [model],
        }},
    )

    assert single["upload_background"] is False
    assert "background" not in single
    assert batch[0]["upload_background"] is False
    assert "background" not in batch[0]


def test_background_is_required_when_switch_is_on():
    model = "data/pic/8baed76edd10056ba355fbe2bdacf963.png"
    workflow = {"name": "人物替换", "inputs": person_replace_inputs()}

    with pytest.raises(ValueError, match="替换背景图"):
        server._resolve_workflow_inputs(
            workflow, {"upload_background": True, "model": model},
        )
    with pytest.raises(ValueError, match="替换背景图"):
        server._resolve_batch_workflow_inputs(
            workflow,
            {"inputs": {
                "upload_background": [True], "background": [],
                "model": [model],
            }},
        )
