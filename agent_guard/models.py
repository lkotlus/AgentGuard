"""
Datclasses, enums, and whatnot.
"""

from datetime import datetime
from dataclasses import dataclass, fields
from enum import Enum
from pathlib import Path
from typing import Any


class Status(Enum):
    ERROR   = "error"
    SUCCESS = "success"
    BLOCKED = "blocked"


@dataclass
class TrackedFile:
    mirror: Path
    offset: int = 0
    tail_start: int = 0
    tail: bytes = b""


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
    annotations: list[str]

    @classmethod
    def from_dict(cls, line: dict) -> "LogLine":
        c = cls(**line)
        c.result_status = Status(line["result_status"])
        c.timestamp = datetime.fromisoformat(line["timestamp"])
        return c


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


@dataclass(frozen=True)
class Confidences:
    path_traversal: float = 0.0

    @property
    def overall(self) -> float:
        product = 1.0
        for field in fields(self):
            v = getattr(self, field.name)
            if not (0.0 <= v <= 1.0):
                raise ValueError(f"{field.name} must be in [0,1], got {v}")

            product *= (1 - float(getattr(self, field.name)))

        return 1 - product
