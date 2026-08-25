"""
RunningHub Cloud ComfyUI — Browser Automation Client
"""

from .browser import BrowserRunner
from .workflow_specs import (
    CompletionSpec,
    NodeModeSpec,
    OutputSpec,
    TextInputSpec,
    UploadSpec,
    WidgetInputSpec,
    WorkflowSpec,
    workflow_spec_from_dict,
)

__all__ = [
    "BrowserRunner",
    "WorkflowSpec",
    "UploadSpec",
    "OutputSpec",
    "CompletionSpec",
    "NodeModeSpec",
    "TextInputSpec",
    "WidgetInputSpec",
    "workflow_spec_from_dict",
]
