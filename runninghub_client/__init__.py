"""
RunningHub Cloud ComfyUI — Browser Automation Client
"""

from .browser import BrowserRunner
from .workflow_specs import (
    ACTION_TRANSFER_SPEC,
    CompletionSpec,
    OutputSpec,
    UploadSpec,
    WorkflowSpec,
    get_workflow_spec,
)

__all__ = [
    "BrowserRunner",
    "WorkflowSpec",
    "UploadSpec",
    "OutputSpec",
    "CompletionSpec",
    "ACTION_TRANSFER_SPEC",
    "get_workflow_spec",
]
