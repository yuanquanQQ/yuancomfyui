"""Declarative differences between RunningHub ComfyUI workflows."""

from dataclasses import dataclass, field
from typing import Any, Mapping, Optional, Sequence


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
class WidgetInputSpec:
    """Map one logical boolean or numeric input to a ComfyUI node widget."""

    key: str
    node_id: str
    widget: str
    label: str
    true_value: Any = "yes"
    false_value: Any = "no"
    required: bool = True
    default: Optional[Any] = None
    interaction: str = "value"
    value_type: str = "boolean"


@dataclass(frozen=True)
class NodeModeSpec:
    """Set one ComfyUI node's fixed execution mode before running."""

    node_id: str
    mode: int
    label: str


@dataclass(frozen=True)
class CompletionSpec:
    """Visible UI markers that authoritatively mean a run has finished."""

    markers: Sequence[str] = ("显示报告", "Show Report")
    minimum_run_seconds: int = 300
    ignore_task_failure: bool = False


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
    widgets: Sequence[WidgetInputSpec] = ()
    node_modes: Sequence[NodeModeSpec] = ()
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

    def resolve_widgets(self, inputs: Mapping[str, Any]):
        resolved = []
        for widget_input in self.widgets:
            raw_value = inputs.get(widget_input.key, widget_input.default)
            if raw_value is None:
                if widget_input.required:
                    raise ValueError(
                        f"Workflow {self.name!r} requires input "
                        f"{widget_input.key!r}"
                    )
                continue
            if widget_input.value_type in {"number", "integer"}:
                if isinstance(raw_value, bool):
                    raise ValueError(
                        f"Workflow {self.name!r} input "
                        f"{widget_input.key!r} must be numeric"
                    )
                try:
                    numeric = float(raw_value)
                except (TypeError, ValueError) as exc:
                    raise ValueError(
                        f"Workflow {self.name!r} input "
                        f"{widget_input.key!r} must be numeric"
                    ) from exc
                if widget_input.value_type == "integer":
                    if not numeric.is_integer():
                        raise ValueError(
                            f"Workflow {self.name!r} input "
                            f"{widget_input.key!r} must be an integer"
                        )
                    value = int(numeric)
                else:
                    value = numeric
                resolved.append((widget_input, value))
                continue
            if isinstance(raw_value, bool):
                enabled = raw_value
            elif isinstance(raw_value, (int, float)) and raw_value in (0, 1):
                enabled = bool(raw_value)
            elif isinstance(raw_value, str):
                normalized = raw_value.strip().lower()
                if normalized in {"true", "yes", "1", "on", "是"}:
                    enabled = True
                elif normalized in {"false", "no", "0", "off", "否"}:
                    enabled = False
                else:
                    raise ValueError(
                        f"Workflow {self.name!r} input "
                        f"{widget_input.key!r} must be boolean"
                    )
            else:
                raise ValueError(
                    f"Workflow {self.name!r} input "
                    f"{widget_input.key!r} must be boolean"
                )
            value = (
                widget_input.true_value if enabled
                else widget_input.false_value
            )
            resolved.append((widget_input, value))
        return resolved


def workflow_spec_from_dict(data: Mapping) -> WorkflowSpec:
    """Build the generic runner configuration returned by the license server."""
    try:
        uploads = tuple(UploadSpec(**item) for item in data.get("uploads", ()))
        texts = tuple(TextInputSpec(**item) for item in data.get("texts", ()))
        widgets = tuple(
            WidgetInputSpec(**item) for item in data.get("widgets", ())
        )
        node_modes = tuple(
            NodeModeSpec(
                node_id=str(item["node_id"]),
                mode=int(item["mode"]),
                label=str(item.get("label") or f"Node {item['node_id']}"),
            )
            for item in data.get("node_modes", ())
        )
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
            ignore_task_failure=bool(
                completion_data.get("ignore_task_failure", False)
            ),
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
        widgets=widgets,
        node_modes=node_modes,
        completion=completion,
        strict_outputs=bool(data.get("strict_outputs", False)),
    )
