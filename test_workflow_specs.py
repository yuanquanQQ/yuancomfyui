import pytest

from runninghub_client.workflow_specs import (
    ANIMATE_TRANSFER_SPEC,
    HD_RESTORE_SPEC,
    OOTD_7DAY_SPEC,
    PERSON_REPLACE_SPEC,
    QWEN_PROMPT_IMAGE_SPEC,
    QWEN_TRYON_SPEC,
    SCAIL_MULTI_REFERENCE_SPEC,
    SCAIL_SEVEN_OUTFIT_SPEC,
)


def test_person_replace_uses_reference_video_and_final_output_only():
    assert [
        (upload.key, upload.node_id, upload.file_widget)
        for upload in PERSON_REPLACE_SPEC.uploads
    ] == [
        ("model", "108", "image"),
        ("video", "112", "video"),
    ]
    assert PERSON_REPLACE_SPEC.strict_outputs is True
    assert len(PERSON_REPLACE_SPEC.outputs) == 1
    output = PERSON_REPLACE_SPEC.outputs[0]
    assert output.node_id == "119"
    assert output.media_type == "video"


def test_ootd_upload_nodes_are_in_day_order():
    assert [upload.key for upload in OOTD_7DAY_SPEC.uploads] == [
        "day1", "day2", "day3", "day4", "day5", "day6", "day7", "audio",
    ]
    assert [upload.node_id for upload in OOTD_7DAY_SPEC.uploads] == [
        "6557", "6798", "6851", "7110", "7170", "7786", "7852", "6726",
    ]


def test_ootd_keeps_only_final_video_output():
    assert OOTD_7DAY_SPEC.strict_outputs is True
    assert len(OOTD_7DAY_SPEC.outputs) == 1
    output = OOTD_7DAY_SPEC.outputs[0]
    assert output.node_id == "6223"
    assert output.media_type == "video"


def test_ootd_requires_all_seven_images_and_audio():
    inputs = {f"day{day}": f"day{day}.png" for day in range(1, 8)}
    with pytest.raises(ValueError, match="audio"):
        OOTD_7DAY_SPEC.resolve_uploads(inputs)

    inputs["audio"] = "music.mp3"
    resolved = OOTD_7DAY_SPEC.resolve_uploads(inputs)
    assert [path for _, path in resolved] == [
        "day1.png", "day2.png", "day3.png", "day4.png",
        "day5.png", "day6.png", "day7.png", "music.mp3",
    ]


def test_qwen_tryon_uses_person_and_garment_inputs():
    assert [upload.key for upload in QWEN_TRYON_SPEC.uploads] == [
        "person", "garment",
    ]
    assert [upload.node_id for upload in QWEN_TRYON_SPEC.uploads] == [
        "23", "24",
    ]


def test_qwen_tryon_keeps_only_final_image():
    assert QWEN_TRYON_SPEC.strict_outputs is True
    assert len(QWEN_TRYON_SPEC.outputs) == 1
    output = QWEN_TRYON_SPEC.outputs[0]
    assert output.node_id == "37"
    assert output.media_type == "image"
    assert output.menu_actions[0] == "save image"


def test_hd_restore_uses_final_upscaled_image_only():
    assert [(upload.key, upload.node_id) for upload in HD_RESTORE_SPEC.uploads] == [
        ("image", "105"),
    ]
    assert HD_RESTORE_SPEC.strict_outputs is True
    assert len(HD_RESTORE_SPEC.outputs) == 1
    output = HD_RESTORE_SPEC.outputs[0]
    assert output.node_id == "149"
    assert output.media_type == "image"
    assert HD_RESTORE_SPEC.completion.markers == ("显示报告", "Show Report")
    assert HD_RESTORE_SPEC.completion.minimum_run_seconds == 0


def test_animate_transfer_uploads_motion_and_reference_inputs():
    assert [
        (upload.key, upload.node_id, upload.file_widget)
        for upload in ANIMATE_TRANSFER_SPEC.uploads
    ] == [
        ("motion_video", "275", "video"),
        ("reference_image", "299", "image"),
    ]
    assert ANIMATE_TRANSFER_SPEC.strict_outputs is True
    assert len(ANIMATE_TRANSFER_SPEC.outputs) == 1
    output = ANIMATE_TRANSFER_SPEC.outputs[0]
    assert output.node_id == "500"
    assert output.media_type == "video"


def test_qwen_prompt_image_uses_generated_image_output():
    assert [
        (upload.key, upload.node_id)
        for upload in QWEN_PROMPT_IMAGE_SPEC.uploads
    ] == [("reference", "100")]
    assert QWEN_PROMPT_IMAGE_SPEC.strict_outputs is True
    assert len(QWEN_PROMPT_IMAGE_SPEC.outputs) == 1
    output = QWEN_PROMPT_IMAGE_SPEC.outputs[0]
    assert output.node_id == "158"
    assert output.media_type == "image"


def test_scail_multi_reference_uses_all_inputs_and_final_video_only():
    assert [
        (upload.key, upload.node_id)
        for upload in SCAIL_MULTI_REFERENCE_SPEC.uploads
    ] == [
        ("motion_video", "214"),
        ("reference1", "1166"),
        ("reference2", "1244"),
        ("reference3", "1336"),
        ("reference4", "1337"),
        ("reference5", "1338"),
        ("reference6", "1339"),
    ]
    assert SCAIL_MULTI_REFERENCE_SPEC.strict_outputs is True
    assert len(SCAIL_MULTI_REFERENCE_SPEC.outputs) == 1
    output = SCAIL_MULTI_REFERENCE_SPEC.outputs[0]
    assert output.node_id == "161"
    assert output.media_type == "video"


def test_scail_seven_outfit_uses_seven_images_and_final_video_only():
    assert [
        (upload.key, upload.node_id)
        for upload in SCAIL_SEVEN_OUTFIT_SPEC.uploads
    ] == [
        ("motion_video", "33"),
        ("outfit1", "30"),
        ("outfit2", "248"),
        ("outfit3", "461"),
        ("outfit4", "462"),
        ("outfit5", "464"),
        ("outfit6", "465"),
        ("outfit7", "466"),
    ]
    assert SCAIL_SEVEN_OUTFIT_SPEC.strict_outputs is True
    assert len(SCAIL_SEVEN_OUTFIT_SPEC.outputs) == 1
    output = SCAIL_SEVEN_OUTFIT_SPEC.outputs[0]
    assert output.node_id == "670"
    assert output.media_type == "video"
    assert SCAIL_SEVEN_OUTFIT_SPEC.completion.markers == ("显示报告", "Show Report")
    assert SCAIL_SEVEN_OUTFIT_SPEC.completion.minimum_run_seconds == 0
