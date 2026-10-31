"""
Datclasses, enums, and whatnot.
"""

from datetime import datetime
from dataclasses import dataclass, field, fields
from enum import Enum
from pathlib import Path
from typing import Any, Literal


#
# Log tracking
#


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
    annotations: list[str] = field(default_factory=list)

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
    session_id: str

    @classmethod
    def from_log_line(cls, line: LogLine) -> "AgentView":
        return cls(**{f: getattr(line, f) for f in cls.__dataclass_fields__})

#
# Scoring
#


@dataclass(frozen=True)
class Confidences:
    tool_risk: float = 0.0
    path_traversal: float = 0.0
    argument_injection: float = 0.0

    @property
    def overall(self) -> float:
        product = 1.0
        for field in fields(self):
            v = getattr(self, field.name)
            if not (0.0 <= v <= 1.0):
                raise ValueError(f"{field.name} must be in [0,1], got {v}")

            product *= (1 - float(getattr(self, field.name)))

        return 1 - product

    def signatures(self) -> list[str]:
        """Names of the signature checks (required for the clanker)"""
        return [f.name for f in fields(self) if f.name != "tool_risk" and getattr(self, f.name) >= 0.5]


TOOL_RISK: dict[tuple[str, str], float] = {
    ("git", "git_commit"): 0.3,
    ("filesystem", "write_file"): 0.3,
    ("memory", "memory_set"): 0.3,
    ("fetch", "fetch"): 0.2,
    ("git", "git_add"): 0.2,
    ("git", "git_init"): 0.2,
}
LOW_RISK_TOOLS = {
    ("filesystem", "read_text_file"), ("filesystem", "list_directory"),
    ("filesystem", "search_files"), ("filesystem", "get_file_info"),
    ("git", "git_status"), ("git", "git_log"), ("git", "git_branch"),
    ("git", "git_diff"), ("git", "git_show_worktree"), ("memory", "memory_get"),
    ("memory", "memory_list"), ("fetch", "list_available_pages")
}
LOW_RISK = 0.05
UNKNOWN_TOOL_RISK = 0.3


#
# RAG
#


@dataclass(frozen=True)
class Finding:
    seq: int
    source: str
    label: str
    detail: str


#
# Reporting
#

Decision = Literal["suppressed", "reviewing", "cleared", "alert", "error"]


class Level(Enum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


@dataclass
class Event:
    kind: Literal["call", "integrity", "system"]
    time: str
    level: Level = Level.INFO
    session_id: str | None = None
    seq: int | None = None
    tool: str | None = None
    target: str | None = None
    decision: Decision | None = None
    source: str | None = None   # signature or analyst
    score: float | None = None
    label: str | None = None    # signature names or analyst category
    evidence: list[int] = field(default_factory=list)
    reasoning: str | None = None
    message: str | None = None


@dataclass
class Row:
    seq: int
    tool: str
    target: str
    score: float
    decision: Decision
    source: str | None = None
    label: str | None = None
    evidence: list[int] = field(default_factory=list)
    reasoning: str | None = None
    linked_by: set[int] = field(default_factory=set)


@dataclass
class Snapshot:
    sessions: dict[str, dict[int, Row]]
    order: list[str]    # session ids in decending order of recency
    integrity: list[Event]
    notices: list[Event]
