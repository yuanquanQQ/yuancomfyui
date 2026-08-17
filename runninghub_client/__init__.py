"""
RunningHub Cloud ComfyUI — Browser Automation Client
"""

from .browser import BrowserRunner
from .workflow_specs import (
    ACTION_TRANSFER_SPEC,
    ANIMATE_TRANSFER_SPEC,
    CompletionSpec,
    HD_RESTORE_SPEC,
    OOTD_7DAY_SPEC,
    OutputSpec,
    QWEN_PROMPT_IMAGE_SPEC,
    QWEN_TRYON_SPEC,
    SCAIL_MULTI_REFERENCE_SPEC,
    SCAIL_SEVEN_OUTFIT_SPEC,
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
    "HD_RESTORE_SPEC",
    "ACTION_TRANSFER_SPEC",
    "ANIMATE_TRANSFER_SPEC",
    "OOTD_7DAY_SPEC",
    "QWEN_PROMPT_IMAGE_SPEC",
    "QWEN_TRYON_SPEC",
    "SCAIL_MULTI_REFERENCE_SPEC",
    "SCAIL_SEVEN_OUTFIT_SPEC",
    "get_workflow_spec",
]
