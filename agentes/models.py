from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


class FlexibleModel(BaseModel):
    model_config = ConfigDict(extra="allow")


class RunTask(FlexibleModel):
    type: str
    summary: str
    input_path: Optional[str] = None


class RunContext(FlexibleModel):
    project: Optional[str] = None
    repo: Optional[str] = None


class TraceRef(FlexibleModel):
    id: str
    path: str


class RunManifest(FlexibleModel):
    schema_version: int = 1
    id: str
    object_type: str = "run"
    task: RunTask
    context: RunContext = Field(default_factory=RunContext)
    status: str = "running"
    trace: TraceRef
    transcript: Optional[TraceRef] = None
    created_at: str
    finished_at: Optional[str] = None


class TraceEvent(FlexibleModel):
    step: int
    type: str
    summary: str
    timestamp: str
    role: Optional[str] = None
    content: Optional[str] = None
    visibility: Optional[str] = None
    sensitivity: Optional[str] = None
    command: Optional[str] = None
    exit_code: Optional[int] = None
    stdout_path: Optional[str] = None
    stderr_path: Optional[str] = None
    transcript_seq: Optional[int] = None
    observations: Optional[List[str]] = None
    hypotheses: Optional[List[str]] = None
    decisions: Optional[List[str]] = None
    rejected_alternatives: Optional[List[Dict[str, str]]] = None
    diagnosis: Optional[str] = None
    linked_evidence: Optional[List[str]] = None


class TranscriptEvent(FlexibleModel):
    seq: int
    type: str
    timestamp: str
    role: Optional[str] = None
    content: Optional[str] = None
    tool: Optional[str] = None
    command: Optional[str] = None
    exit_code: Optional[int] = None
    summary: Optional[str] = None
    stdout_path: Optional[str] = None
    stderr_path: Optional[str] = None
    visibility: str = "visible"
    sensitivity: str = "normal"
    linked_evidence: Optional[List[str]] = None


class EvidenceSource(FlexibleModel):
    run: str
    trace_step: Optional[int] = None


class EvidenceData(FlexibleModel):
    command: Optional[str] = None
    exit_code: Optional[int] = None
    stdout_path: Optional[str] = None
    stderr_path: Optional[str] = None


class EvidenceManifest(FlexibleModel):
    schema_version: int = 1
    id: str
    object_type: str = "evidence"
    type: str
    claim: str
    strength: str = "medium"
    source: EvidenceSource
    data: EvidenceData = Field(default_factory=EvidenceData)
    created_at: str

    @field_validator("strength")
    @classmethod
    def strength_must_be_known(cls, value: str) -> str:
        known = {"weak", "medium", "strong"}
        if value not in known:
            raise ValueError(f"strength must be one of {sorted(known)}")
        return value


class ExperienceManifest(FlexibleModel):
    schema_version: int = 1
    id: Optional[str] = None
    object_type: str = "experience"
    status: str = "success"
    confidence: str = "medium"
    task: Dict[str, Any] = Field(default_factory=dict)
    problem: Dict[str, Any] = Field(default_factory=dict)
    context: Dict[str, Any] = Field(default_factory=dict)
    actions: Dict[str, Any] = Field(default_factory=dict)
    outcome: Dict[str, Any] = Field(default_factory=dict)
    diagnosis: Dict[str, Any] = Field(default_factory=dict)
    reuse: Dict[str, Any] = Field(default_factory=dict)
    evidence: Dict[str, Any] = Field(default_factory=dict)
    provenance: Dict[str, Any] = Field(default_factory=dict)
    lifecycle: Dict[str, Any] = Field(default_factory=dict)

    @field_validator("status")
    @classmethod
    def status_must_be_known(cls, value: str) -> str:
        known = {"success", "failure", "partial", "warning", "deprecated"}
        if value not in known:
            raise ValueError(f"status must be one of {sorted(known)}")
        return value

    @field_validator("confidence")
    @classmethod
    def confidence_must_be_known(cls, value: str) -> str:
        known = {"low", "medium", "high"}
        if value not in known:
            raise ValueError(f"confidence must be one of {sorted(known)}")
        return value


class CurrentContext(FlexibleModel):
    task_type: Optional[str] = None
    domain: Optional[str] = None
    project: Optional[str] = None
    repo: Optional[str] = None
    symptoms: List[str] = Field(default_factory=list)
    environment: Dict[str, Any] = Field(default_factory=dict)
    observed: List[str] = Field(default_factory=list)


class ReuseEvent(FlexibleModel):
    id: str
    experience_id: str
    run_id: Optional[str] = None
    result: str
    notes: str = ""
    created_at: str
