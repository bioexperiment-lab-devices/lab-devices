"""Declarative experiment-orchestration layer on top of lab_devices. See design §1."""

from __future__ import annotations

from lab_devices.experiment.analyze import (
    BindingType,
    ExprRefs,
    ExprType,
    TypeReport,
    infer_type,
    references,
)
from lab_devices.experiment.blocks import (
    Block,
    Branch,
    Command,
    GroupRef,
    Loop,
    Measure,
    OperatorInput,
    Parallel,
    Serial,
    Wait,
)
from lab_devices.experiment.durations import parse_duration
from lab_devices.experiment.errors import (
    Diagnostic,
    EvaluationError,
    ExperimentError,
    ExpressionError,
    UnknownVerbError,
    ValidationError,
    WorkflowLoadError,
)
from lab_devices.experiment.evaluate import Value, evaluate, resolve
from lab_devices.experiment.expr import (
    AllWindow,
    BinaryOp,
    BindingRef,
    Const,
    DurationWindow,
    Expr,
    SampleWindow,
    StatCall,
    UnaryOp,
    Window,
    parse_expression,
)
from lab_devices.experiment.serialize import (
    SCHEMA_VERSION,
    block_from_dict,
    block_to_dict,
    load_workflow,
    save_workflow,
    workflow_from_dict,
    workflow_to_dict,
)
from lab_devices.experiment.state import BindingValue, RunState, Sample, Stream
from lab_devices.experiment.validate import load_and_validate, validate
from lab_devices.experiment.workflow import (
    Group,
    Metadata,
    Persistence,
    StreamDecl,
    Workflow,
)

__all__ = [
    "BindingType", "Diagnostic", "ExprRefs", "ExprType", "TypeReport",
    "ValidationError", "infer_type", "load_and_validate", "references", "validate",
    "Block", "Branch", "Command", "GroupRef", "Loop", "Measure", "OperatorInput",
    "Parallel", "Serial", "Wait",
    "EvaluationError", "ExperimentError", "ExpressionError", "UnknownVerbError",
    "WorkflowLoadError",
    "block_from_dict", "block_to_dict", "load_workflow", "save_workflow",
    "workflow_from_dict", "workflow_to_dict", "SCHEMA_VERSION",
    "Group", "Metadata", "Persistence", "StreamDecl", "Workflow",
    "AllWindow", "BinaryOp", "BindingRef", "Const", "DurationWindow", "Expr",
    "SampleWindow", "StatCall", "UnaryOp", "Window", "parse_expression", "parse_duration",
    "BindingValue", "RunState", "Sample", "Stream",
    "Value", "evaluate", "resolve",
]
