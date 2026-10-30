"""
This is where the magic happens. Signature-based results 
get dispatched to agents, which then further evaluate based on
other evidence.
"""

from pathlib import Path

from agent_guard.models import LogLine, AgentView, Confidences
from agent_guard.registry import registry


PATH_ARGS = ["target_path", "path"]


def dispatch_finding(server_cwd: Path, allowed_path: Path, log: LogLine) -> None:
    """Dispatches to agent."""
    confidences = Confidences(
        path_traversal=validate_path(server_cwd, allowed_path, log)
    )
    agent_log = AgentView.from_log_line(log)

    if confidences.overall > 0.8:
        print(f"Anomalous log (high signature match, seq {log.seq}):\n\t{log}\n\t{confidences}\n")
    else:
        registry.dispatch(log, agent_log, confidences)

    
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
