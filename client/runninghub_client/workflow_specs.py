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


def workflow_spec_from_dict(data: Mapping) -> WorkflowSpec:
    """Build the generic runner configuration returned by the license server."""
    try:
        uploads = tuple(UploadSpec(**item) for item in data.get("uploads", ()))
        texts = tuple(TextInputSpec(**item) for item in data.get("texts", ()))
        outputs = tuple(
            OutputSpec(
                node_id=str(item["node_id"]),
                menu_actions=tuple(item.get("menu_actions") or ()),
                media_type=str(item.get("media_type") or "video"),
            )
            for item in data.get("outputs", ())
        )
        completion_data = data.get("completion") or {}
        completion = CompletionSpec(
            markers=tuple(completion_data.get("markers") or ("显示报告", "Show Report")),
            minimum_run_seconds=int(completion_data.get("minimum_run_seconds", 300)),
        )
        name = str(data["name"]).strip()
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("服务器返回的工作流执行配置无效") from exc
    if not name or not outputs:
        raise ValueError("服务器返回的工作流执行配置不完整")
    return WorkflowSpec(
        name=name,
        uploads=uploads,
        outputs=outputs,
        texts=texts,
        completion=completion,
        strict_outputs=bool(data.get("strict_outputs", False)),
    )
