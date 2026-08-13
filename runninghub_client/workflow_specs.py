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
class CompletionSpec:
    """Visible UI markers that authoritatively mean a run has finished."""

    markers: Sequence[str] = ("显示报告", "Show Report")
    minimum_run_seconds: int = 300


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
        UploadSpec("model", "108", "upload", "人物参考图", "image"),
        UploadSpec("video", "112", "choose video to upload", "动作视频", "video"),
    ),
    outputs=(
        OutputSpec(node_id="119", menu_actions=("save video", "save preview"), media_type="video"),
    ),
    strict_outputs=True,
)

WORKFLOW_SPECS = {
    ACTION_TRANSFER_SPEC.name: ACTION_TRANSFER_SPEC,
    PERSON_REPLACE_SPEC.name: PERSON_REPLACE_SPEC,
}


def get_workflow_spec(name: str) -> WorkflowSpec:
    try:
        return WORKFLOW_SPECS[name]
    except KeyError as exc:
        raise ValueError(f"Unknown workflow spec: {name}") from exc
