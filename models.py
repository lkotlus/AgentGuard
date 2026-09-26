"""
Datclasses, enums, and whatnot.
"""

from datetime import datetime
from dataclasses import dataclass
from enum import Enum
from typing import Any


class Status(Enum):
    ERROR   = "error"
    SUCCESS = "success"
    BLOCKED = "blocked"


@dataclass
class LogLine:
    arguments: dict[str, Any]
    result_status: Status
    result_summary: str
    server: str
    tool_name: str
    target_resource: str
    seq: int
    timestamp: datetime
    duration_ms: float
    task_id: str
    session_id: str
    scenario_tag: str


@dataclass(frozen=True)
class AgentView:
    arguments: dict[str, Any]
    result_status: Status
    result_summary: str
    server: str
    tool_name: str
    target_resource: str
    seq: int
    timestamp: datetime
    duration_ms: float
    task_id: str
    session_id: str

    @classmethod
    def from_log_line(cls, line: LogLine) -> "AgentView":
        return cls(**{f: getattr(line, f) for f in cls.__dataclass_fields__})
