import pytest

from runninghub_client.workflow_specs import workflow_spec_from_dict


def sample_config():
    return {
        "name": "remote_workflow",
        "uploads": [{
            "key": "source", "node_id": "10", "button_widget": "upload",
            "label": "源文件", "file_widget": "image", "required": True,
        }],
        "texts": [{
            "key": "prompt", "node_id": "20", "widget": "text",
            "label": "提示词", "required": True,
        }],
        "widgets": [{
            "key": "upload_background", "node_id": "250",
            "widget": "RGTHREE_TOGGLE_AND_NAV", "label": "上传替换背景",
            "true_value": True, "false_value": False, "required": True,
            "default": True,
            "interaction": "rgthree_toggle",
        }],
        "node_modes": [{
            "node_id": "1336", "mode": 2, "label": "参考图节点 1336",
        }],
        "outputs": [{
            "node_id": "30", "menu_actions": ["save image"],
            "media_type": "image",
        }],
        "completion": {
            "markers": ["显示报告", "Show Report"],
            "minimum_run_seconds": 30,
            "ignore_task_failure": True,
        },
        "strict_outputs": True,
    }


def test_builds_runtime_spec_from_server_payload():
    spec = workflow_spec_from_dict(sample_config())

    assert spec.name == "remote_workflow"
    assert spec.uploads[0].node_id == "10"
    assert spec.texts[0].node_id == "20"
    assert spec.widgets[0].node_id == "250"
    assert spec.node_modes[0].node_id == "1336"
    assert spec.node_modes[0].mode == 2
    assert spec.outputs[0].node_id == "30"
    assert spec.completion.minimum_run_seconds == 30
    assert spec.completion.ignore_task_failure is True
    assert spec.strict_outputs is True


def test_server_spec_enforces_required_inputs():
    spec = workflow_spec_from_dict(sample_config())

    with pytest.raises(ValueError, match="source"):
        spec.resolve_uploads({"prompt": "hello"})
    with pytest.raises(ValueError, match="prompt"):
        spec.resolve_texts({"source": "source.png"})


def test_rejects_server_spec_without_output():
    config = sample_config()
    config["outputs"] = []

    with pytest.raises(ValueError, match="不完整"):
        workflow_spec_from_dict(config)


def test_boolean_widget_values_are_mapped_for_comfyui():
    spec = workflow_spec_from_dict(sample_config())

    assert spec.resolve_widgets({"upload_background": True})[0][1] is True
    assert spec.resolve_widgets({"upload_background": "no"})[0][1] is False
    assert spec.resolve_widgets({})[0][1] is True
    with pytest.raises(ValueError, match="must be boolean"):
        spec.resolve_widgets({"upload_background": "sometimes"})


def test_numeric_widget_values_are_preserved_for_comfyui():
    config = sample_config()
    config["widgets"] = [
        {
            "key": "motion_strength", "node_id": "266",
            "widget": "value", "label": "动作幅度",
            "value_type": "number", "default": 0.2,
        },
        {
            "key": "frame_load_cap", "node_id": "422",
            "widget": "value", "label": "加载帧数上限",
            "value_type": "integer", "default": 900,
        },
    ]
    spec = workflow_spec_from_dict(config)

    assert [value for _, value in spec.resolve_widgets({})] == [0.2, 900]
    assert [value for _, value in spec.resolve_widgets({
        "motion_strength": "0.35", "frame_load_cap": "720",
    })] == [0.35, 720]
    with pytest.raises(ValueError, match="integer"):
        spec.resolve_widgets({"motion_strength": 0.2, "frame_load_cap": 12.5})
