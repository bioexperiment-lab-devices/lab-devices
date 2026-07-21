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
    Compute,
    ForEach,
    GroupRef,
    Loop,
    Measure,
    OperatorInput,
    Parallel,
    Record,
    Retry,
    Serial,
    Wait,
)
from lab_devices.experiment.catalog import (
    ParamEntry,
    VerbEntry,
    expression_functions,
    verb_catalog,
)
from lab_devices.experiment.clock import Clock, MonotonicClock
from lab_devices.experiment.context import RunOptions
from lab_devices.experiment.control import Console
from lab_devices.experiment.durations import parse_duration
from lab_devices.experiment.errors import (
    AlarmRecord,
    BlockFailedError,
    DeviceBusyError,
    Diagnostic,
    EvaluationError,
    ExperimentError,
    ExperimentRunError,
    ExpressionError,
    FinalizeError,
    InvariantViolationError,
    OrphanedJobError,
    PersistenceError,
    RunAbortedError,
    ToleratedError,
    UnknownRoleError,
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
from lab_devices.experiment.inputs import (
    InputRequest,
    OperatorInputProvider,
    UnattendedInputProvider,
)
from lab_devices.experiment.persist import (
    CsvRunLogSink,
    CsvStreamSink,
    JsonlRunLogSink,
    JsonlStreamSink,
    SinkSet,
    StreamSink,
)
from lab_devices.experiment.run import ExperimentRun, RunReport, assign_block_ids
from lab_devices.experiment.runlog import InMemoryRunLog, RunEvent, RunLogSink
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
from lab_devices.experiment.units import unit_str
from lab_devices.experiment.validate import binding_types, load_and_validate, validate
from lab_devices.experiment.workflow import (
    Defaults,
    Group,
    LocalDecl,
    Metadata,
    ParamDecl,
    Persistence,
    RoleDecl,
    StreamDecl,
    Workflow,
)

__all__ = [
    "BindingType", "Diagnostic", "ExprRefs", "ExprType", "TypeReport",
    "ValidationError", "binding_types", "infer_type", "load_and_validate",
    "references", "unit_str", "validate",
    "Block", "Branch", "Command", "Compute", "ForEach", "GroupRef", "Loop", "Measure",
    "OperatorInput", "Parallel", "Record", "Retry", "Serial", "Wait",
    "EvaluationError", "ExperimentError", "ExpressionError", "UnknownVerbError",
    "UnknownRoleError", "WorkflowLoadError",
    "block_from_dict", "block_to_dict", "load_workflow", "save_workflow",
    "workflow_from_dict", "workflow_to_dict", "SCHEMA_VERSION",
    "Defaults", "Group", "LocalDecl", "Metadata", "ParamDecl", "Persistence",
    "RoleDecl", "StreamDecl", "Workflow",
    "AllWindow", "BinaryOp", "BindingRef", "Const", "DurationWindow", "Expr",
    "SampleWindow", "StatCall", "UnaryOp", "Window", "parse_expression", "parse_duration",
    "BindingValue", "RunState", "Sample", "Stream",
    "Value", "evaluate", "resolve",
    "ExperimentRun", "RunOptions", "RunReport", "assign_block_ids", "Console",
    "Clock", "MonotonicClock",
    "OperatorInputProvider", "InputRequest", "UnattendedInputProvider",
    "RunEvent", "RunLogSink", "InMemoryRunLog",
    "ExperimentRunError", "BlockFailedError", "InvariantViolationError",
    "RunAbortedError", "FinalizeError", "PersistenceError", "DeviceBusyError",
    "OrphanedJobError", "ToleratedError", "AlarmRecord",
    "CsvRunLogSink", "CsvStreamSink", "JsonlRunLogSink", "JsonlStreamSink",
    "SinkSet", "StreamSink",
    "ParamEntry", "VerbEntry", "expression_functions", "verb_catalog",
]
