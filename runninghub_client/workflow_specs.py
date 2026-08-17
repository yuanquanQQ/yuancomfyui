"""Declarative differences between RunningHub ComfyUI workflows."""

from dataclasses import dataclass, field
from typing import Mapping, Optional, Sequence


@dataclass(frozen=True)
class UploadSpec:
    """Map one logical task input to one ComfyUI upload node."""

    key: str
    node_id: str
    button_widget: str
    label: str
    file_widget: Optional[str] = None
    required: bool = True
    fallback_key: Optional[str] = None


@dataclass(frozen=True)
class TextInputSpec:
    """Map one logical text input to one ComfyUI node widget."""

    key: str
    node_id: str
    widget: str
    label: str
    required: bool = True


@dataclass(frozen=True)
class CompletionSpec:
    """Visible UI markers that authoritatively mean a run has finished."""

    markers: Sequence[str] = ("显示报告", "Show Report")
    minimum_run_seconds: int = 300


IMAGE_COMPLETION = CompletionSpec(minimum_run_seconds=30)


@dataclass(frozen=True)
class OutputSpec:
    """How to save a workflow output from a ComfyUI output node."""

    node_id: str
    menu_actions: Sequence[str] = (
        "save preview",
        "save image",
        "save video",
    )
    media_type: str = "video"


@dataclass(frozen=True)
class WorkflowSpec:
    """All workflow-specific browser details used by the generic runner."""

    name: str
    uploads: Sequence[UploadSpec]
    outputs: Sequence[OutputSpec]
    texts: Sequence[TextInputSpec] = ()
    completion: CompletionSpec = field(default_factory=CompletionSpec)
    strict_outputs: bool = False

    def resolve_uploads(self, inputs: Mapping[str, Optional[str]]):
        resolved = []
        for upload in self.uploads:
            path = inputs.get(upload.key)
            if not path and upload.fallback_key:
                path = inputs.get(upload.fallback_key)
            if not path:
                if upload.required:
                    raise ValueError(
                        f"Workflow {self.name!r} requires input {upload.key!r}"
                    )
                continue
            resolved.append((upload, path))
        return resolved

    def resolve_texts(self, inputs: Mapping[str, Optional[str]]):
        resolved = []
        for text_input in self.texts:
            value = str(inputs.get(text_input.key) or "").strip()
            if not value:
                if text_input.required:
                    raise ValueError(
                        f"Workflow {self.name!r} requires input {text_input.key!r}"
                    )
                continue
            resolved.append((text_input, value))
        return resolved


ACTION_TRANSFER_SPEC = WorkflowSpec(
    name="action_transfer",
    uploads=(
        UploadSpec("video", "1055", "choose video to upload", "视频", "video"),
        UploadSpec("model", "1116", "upload", "人物模特", "image"),
        UploadSpec(
            "clothing", "1117", "upload", "衣服", "image",
            fallback_key="model",
        ),
    ),
    outputs=(
        OutputSpec(
            node_id="1058",
            menu_actions=("save preview", "save video"),
            media_type="video",
        ),
    ),
)


PERSON_REPLACE_SPEC = WorkflowSpec(
    name="person_replace",
    uploads=(
        UploadSpec("background", "247", "upload", "替换背景图", "image"),
        UploadSpec("model", "108", "upload", "人物参考图", "image"),
        UploadSpec("video", "112", "choose video to upload", "动作视频", "video"),
    ),
    outputs=(
        OutputSpec(node_id="119", menu_actions=("save video", "save preview"), media_type="video"),
    ),
    strict_outputs=True,
)

OOTD_7DAY_SPEC = WorkflowSpec(
    name="ootd_7day",
    uploads=(
        UploadSpec("day1", "6557", "upload", "第 1 天图片", "image"),
        UploadSpec("day2", "6798", "upload", "第 2 天图片", "image"),
        UploadSpec("day3", "6851", "upload", "第 3 天图片", "image"),
        UploadSpec("day4", "7110", "upload", "第 4 天图片", "image"),
        UploadSpec("day5", "7170", "upload", "第 5 天图片", "image"),
        UploadSpec("day6", "7786", "upload", "第 6 天图片", "image"),
        UploadSpec("day7", "7852", "upload", "第 7 天图片", "image"),
        UploadSpec("audio", "6726", "upload", "背景音乐", "audio"),
    ),
    outputs=(
        OutputSpec(
            node_id="6223",
            menu_actions=("save video", "save preview"),
            media_type="video",
        ),
    ),
    strict_outputs=True,
)

QWEN_TRYON_SPEC = WorkflowSpec(
    name="qwen_tryon",
    uploads=(
        UploadSpec("person", "23", "upload", "人物图片", "image"),
        UploadSpec("garment", "24", "upload", "衣服图片", "image"),
    ),
    outputs=(
        OutputSpec(
            node_id="37",
            menu_actions=("save image", "save preview"),
            media_type="image",
        ),
    ),
    completion=IMAGE_COMPLETION,
    strict_outputs=True,
)

HD_RESTORE_SPEC = WorkflowSpec(
    name="hd_restore",
    uploads=(
        UploadSpec("image", "105", "upload", "待修复图片", "image"),
    ),
    outputs=(
        OutputSpec(
            node_id="149",
            menu_actions=("save image", "save preview"),
            media_type="image",
        ),
    ),
    completion=IMAGE_COMPLETION,
    strict_outputs=True,
)

ANIMATE_TRANSFER_SPEC = WorkflowSpec(
    name="animate_transfer",
    uploads=(
        UploadSpec(
            "motion_video", "275", "choose video to upload",
            "动作视频", "video",
        ),
        UploadSpec("reference_image", "299", "upload", "人物参考图", "image"),
    ),
    outputs=(
        OutputSpec(
            node_id="500",
            menu_actions=("save video", "save preview"),
            media_type="video",
        ),
    ),
    strict_outputs=True,
)

QWEN_PROMPT_IMAGE_SPEC = WorkflowSpec(
    name="qwen_prompt_image",
    uploads=(
        UploadSpec("reference", "100", "upload", "参考图片", "image"),
    ),
    outputs=(
        OutputSpec(
            node_id="161",
            menu_actions=("save image", "save preview"),
            media_type="image",
        ),
    ),
    completion=IMAGE_COMPLETION,
    strict_outputs=True,
)

SCAIL_MULTI_REFERENCE_SPEC = WorkflowSpec(
    name="scail_multi_reference",
    uploads=(
        UploadSpec(
            "motion_video", "214", "choose video to upload",
            "动作视频", "video",
        ),
        UploadSpec("reference1", "1166", "upload", "参考图 1", "image"),
        UploadSpec("reference2", "1244", "upload", "参考图 2", "image"),
        UploadSpec("reference3", "1336", "upload", "参考图 3", "image"),
        UploadSpec("reference4", "1337", "upload", "参考图 4", "image"),
        UploadSpec("reference5", "1338", "upload", "参考图 5", "image"),
        UploadSpec("reference6", "1339", "upload", "参考图 6", "image"),
    ),
    outputs=(
        OutputSpec(
            node_id="161",
            menu_actions=("save video", "save preview"),
            media_type="video",
        ),
    ),
    strict_outputs=True,
)

SCAIL_SEVEN_OUTFIT_SPEC = WorkflowSpec(
    name="scail_seven_outfit",
    uploads=(
        UploadSpec(
            "motion_video", "33", "choose video to upload",
            "动作视频", "video",
        ),
        UploadSpec("outfit1", "30", "upload", "第 1 段贴图", "image"),
        UploadSpec("outfit2", "248", "upload", "第 2 段贴图", "image"),
        UploadSpec("outfit3", "461", "upload", "第 3 段贴图", "image"),
        UploadSpec("outfit4", "462", "upload", "第 4 段贴图", "image"),
        UploadSpec("outfit5", "464", "upload", "第 5 段贴图", "image"),
        UploadSpec("outfit6", "465", "upload", "第 6 段贴图", "image"),
        UploadSpec("outfit7", "466", "upload", "第 7 段贴图", "image"),
    ),
    outputs=(
        OutputSpec(
            node_id="670",
            menu_actions=("save video", "save preview"),
            media_type="video",
        ),
    ),
    completion=CompletionSpec(
        markers=("显示报告", "Show Report"),
        minimum_run_seconds=0,
    ),
    strict_outputs=True,
)

SCAIL_4K_POSE_BACKGROUND_SPEC = WorkflowSpec(
    name="scail_4k_pose_background",
    uploads=(
        UploadSpec("background", "393", "upload", "背景图", "image"),
        UploadSpec("person", "396", "upload", "人物图", "image"),
    ),
    outputs=(
        OutputSpec(
            node_id="391",
            menu_actions=("save image", "save preview"),
            media_type="image",
        ),
    ),
    completion=IMAGE_COMPLETION,
    strict_outputs=True,
)

KREA2_REALISTIC_4K_SPEC = WorkflowSpec(
    name="krea2_realistic_4k",
    uploads=(),
    outputs=(
        OutputSpec(
            node_id="83",
            menu_actions=("save preview", "save image"),
            media_type="image",
        ),
    ),
    texts=(
        TextInputSpec("prompt", "64", "text", "画面提示词"),
    ),
    completion=IMAGE_COMPLETION,
    strict_outputs=True,
)

QWEN_MULTI_VIEW_SPEC = WorkflowSpec(
    name="qwen_multi_view",
    uploads=(
        UploadSpec("character", "61", "upload", "角色参考图", "image"),
    ),
    outputs=(
        OutputSpec(
            node_id="448",
            menu_actions=("save preview", "save image"),
            media_type="image",
        ),
    ),
    completion=IMAGE_COMPLETION,
    strict_outputs=True,
)

WORKFLOW_SPECS = {
    ACTION_TRANSFER_SPEC.name: ACTION_TRANSFER_SPEC,
    PERSON_REPLACE_SPEC.name: PERSON_REPLACE_SPEC,
    OOTD_7DAY_SPEC.name: OOTD_7DAY_SPEC,
    QWEN_TRYON_SPEC.name: QWEN_TRYON_SPEC,
    HD_RESTORE_SPEC.name: HD_RESTORE_SPEC,
    ANIMATE_TRANSFER_SPEC.name: ANIMATE_TRANSFER_SPEC,
    QWEN_PROMPT_IMAGE_SPEC.name: QWEN_PROMPT_IMAGE_SPEC,
    SCAIL_MULTI_REFERENCE_SPEC.name: SCAIL_MULTI_REFERENCE_SPEC,
    SCAIL_SEVEN_OUTFIT_SPEC.name: SCAIL_SEVEN_OUTFIT_SPEC,
    SCAIL_4K_POSE_BACKGROUND_SPEC.name: SCAIL_4K_POSE_BACKGROUND_SPEC,
    KREA2_REALISTIC_4K_SPEC.name: KREA2_REALISTIC_4K_SPEC,
    QWEN_MULTI_VIEW_SPEC.name: QWEN_MULTI_VIEW_SPEC,
}


def get_workflow_spec(name: str) -> WorkflowSpec:
    try:
        return WORKFLOW_SPECS[name]
    except KeyError as exc:
        raise ValueError(f"Unknown workflow spec: {name}") from exc
