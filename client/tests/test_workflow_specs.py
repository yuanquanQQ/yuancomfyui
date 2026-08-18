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
        "outputs": [{
            "node_id": "30", "menu_actions": ["save image"],
            "media_type": "image",
        }],
        "completion": {
            "markers": ["显示报告", "Show Report"],
            "minimum_run_seconds": 30,
        },
        "strict_outputs": True,
    }


def test_builds_runtime_spec_from_server_payload():
    spec = workflow_spec_from_dict(sample_config())

    assert spec.name == "remote_workflow"
    assert spec.uploads[0].node_id == "10"
    assert spec.texts[0].node_id == "20"
    assert spec.outputs[0].node_id == "30"
    assert spec.completion.minimum_run_seconds == 30
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
