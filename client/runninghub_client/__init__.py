"""
RunningHub Cloud ComfyUI — Browser Automation Client
"""

from .browser import BrowserRunner
from .workflow_specs import (
    CompletionSpec,
    OutputSpec,
    TextInputSpec,
    UploadSpec,
    WorkflowSpec,
    workflow_spec_from_dict,
)

__all__ = [
    "BrowserRunner",
    "WorkflowSpec",
    "UploadSpec",
    "OutputSpec",
    "CompletionSpec",
    "TextInputSpec",
    "workflow_spec_from_dict",
]
