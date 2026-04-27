from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field, field_validator


class Severity(StrEnum):
    sev1 = "SEV1"
    sev2 = "SEV2"
    sev3 = "SEV3"
    sev4 = "SEV4"


class TimelineEvent(BaseModel):
    at: datetime
    actor: str = Field(min_length=1, max_length=80)
    action: str = Field(min_length=1, max_length=400)


class ActionItem(BaseModel):
    title: str = Field(min_length=5, max_length=200)
    owner: str = Field(min_length=1)
    priority: Literal["P0", "P1", "P2", "P3"]
    due_window: Literal["this_sprint", "next_sprint", "next_quarter"]


class Postmortem(BaseModel):
    """Google SRE Workbook-shaped postmortem. All fields required."""
    summary: str = Field(min_length=20, max_length=500,
                         description="One paragraph; what happened, when, who was affected.")
    impact: str = Field(min_length=10,
                        description="Users affected, duration, severity dimensions.")
    severity: Severity
    detection: str
    root_cause: str = Field(min_length=20)
    trigger: str
    resolution: str
    timeline: list[TimelineEvent] = Field(min_length=1)
    what_went_well: list[str] = Field(min_length=1, max_length=10)
    what_went_wrong: list[str] = Field(min_length=1, max_length=10)
    action_items: list[ActionItem] = Field(min_length=1, max_length=15)
    lessons_learned: list[str] = Field(min_length=1, max_length=10)

    @field_validator("timeline")
    @classmethod
    def chronological(cls, v: list[TimelineEvent]) -> list[TimelineEvent]:
        if v != sorted(v, key=lambda e: e.at):
            raise ValueError("timeline must be chronological")
        return v


class LogAnalysis(BaseModel):
    """The 5-field log analyzer contract — see FR1 / AT-001."""
    severity: Literal["info", "warning", "critical"]
    summary: str = Field(min_length=10, max_length=400)
    root_cause: str = Field(min_length=10)
    runbook: list[str] = Field(min_length=1, max_length=10)
    related_metrics: list[str] = Field(default_factory=list, max_length=10)


class PostmortemRequest(BaseModel):
    log_analysis: dict
    timeline: list[dict] | None = None
    context: str | None = Field(default=None, max_length=2_000)
