from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


Sentiment = Literal["calm", "stressed", "urgent", "angry", "uncertain", "neutral"]
PolicyMatchStatus = Literal["verified", "unverified", "not_checked"]


class FNOLField(BaseModel):
    value: Any = None
    confidence: float = Field(ge=0.0, le=1.0)
    source_turn_ids: list[int] = Field(default_factory=list)
    needs_followup: bool = True


class PolicyMatch(BaseModel):
    status: PolicyMatchStatus = "not_checked"
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    policy_number: FNOLField = Field(default_factory=lambda: FNOLField(confidence=0.0))
    insured_name: FNOLField = Field(default_factory=lambda: FNOLField(confidence=0.0))
    match_reasons: list[str] = Field(default_factory=list)


class TimelineEvent(BaseModel):
    time_in_call_secs: float | None = None
    turn_id: int | None = None
    event_type: str
    summary: str
    sentiment: Sentiment = "neutral"


class QualityReport(BaseModel):
    completion_score: float = Field(ge=0.0, le=1.0)
    missing_essentials: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)


class CallbackRequest(BaseModel):
    needed: bool = False
    requested_time: datetime | None = None
    timezone: str = "Europe/Berlin"
    notes: str | None = None


class FNOLDocument(BaseModel):
    document_status: str = "Draft FNOL"
    policy_match: PolicyMatch = Field(default_factory=PolicyMatch)
    executive_summary: str
    safety: dict[str, FNOLField] = Field(default_factory=dict)
    caller: dict[str, FNOLField] = Field(default_factory=dict)
    loss: dict[str, FNOLField] = Field(default_factory=dict)
    people: dict[str, FNOLField] = Field(default_factory=dict)
    vehicles: dict[str, FNOLField] = Field(default_factory=dict)
    police: dict[str, FNOLField] = Field(default_factory=dict)
    witnesses: dict[str, FNOLField] = Field(default_factory=dict)
    coverage: dict[str, FNOLField] = Field(default_factory=dict)
    evidence: dict[str, FNOLField] = Field(default_factory=dict)
    resolution: dict[str, FNOLField] = Field(default_factory=dict)
    timeline: list[TimelineEvent] = Field(default_factory=list)
    quality: QualityReport
    callback: CallbackRequest = Field(default_factory=CallbackRequest)
