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
