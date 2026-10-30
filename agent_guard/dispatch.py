"""
This is where the magic happens. Signature-based results 
get dispatched to agents, which then further evaluate based on
other evidence.
"""

from pathlib import Path

from agent_guard.models import LOW_RISK, LOW_RISK_TOOLS, TOOL_RISK, UNKNOWN_TOOL_RISK, LogLine, AgentView, Confidences
from agent_guard.registry import registry


PATH_ARGS = ["target_path", "path"]
ALERT_THRESH = 0.8
REVIEW_THRESH = 0.2


def dispatch_finding(server_cwd: Path, allowed_path: Path, log: LogLine) -> None:
    """Dispatches to agent."""
    confidences = Confidences(
        tool_risk=tool_risk(log.server, log.tool_name),
        path_traversal=validate_path(server_cwd, allowed_path, log)
    )
    agent_log = AgentView.from_log_line(log)

    if confidences.overall > ALERT_THRESH:
        print(f"Anomalous log (high signature match, seq {log.seq}):\n\t{log}\n\t{confidences}\n")
    elif confidences.overall > REVIEW_THRESH:
        registry.dispatch(log, agent_log, confidences)
    else:
        print(f"Suppressed log seq {log.seq} from {log.session_id} (confidence below {REVIEW_THRESH*100}%)")


def tool_risk(server: str, tool_name: str) -> float:
    if (server, tool_name) in TOOL_RISK:
        return TOOL_RISK[(server, tool_name)]
    if (server, tool_name) in LOW_RISK_TOOLS:
        return LOW_RISK
    return UNKNOWN_TOOL_RISK

    
def extract_paths(server_cwd: Path, allowed_path: Path, fline: LogLine) -> list[tuple[str, Path]]:
    """Returns (path, base the server resolves it against) pairs."""
    base = server_cwd if fline.tool_name == "git_init" else allowed_path
    return [(str(fline.arguments[a]), base) for a in PATH_ARGS if a in fline.arguments]


def validate_path(server_cwd: Path, allowed_path: Path, fline: LogLine) -> float:
    """Binary check for path traversal attempts."""
    for p, base in extract_paths(server_cwd, allowed_path, fline):
        if not (base / p).resolve().is_relative_to(allowed_path):
            return 1.0
    return 0.0
