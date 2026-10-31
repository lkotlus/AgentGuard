"""
This is where the magic happens. Signature-based results 
get dispatched to agents, which then further evaluate based on
other evidence.
"""

from pathlib import Path
from typing import Any

from agent_guard.models import (
    LOW_RISK,
    LOW_RISK_TOOLS,
    TOOL_RISK,
    UNKNOWN_TOOL_RISK,
    LogLine,
    AgentView,
    Confidences
)
from agent_guard.registry import registry
from agent_guard.reporting import reporter


PATH_ARGS = ["target_path", "path"]
GIT_DIFF = ("git", "git_diff")
OUTPUT_OPT = "--output"

ALERT_THRESH = 0.8
REVIEW_THRESH = 0.1


def dispatch_finding(server_cwd: Path, allowed_path: Path, log: LogLine) -> None:
    """Scores a log and passes it to the registry."""
    confidences = Confidences(
        tool_risk=tool_risk(log.server, log.tool_name),
        path_traversal=validate_path(server_cwd, allowed_path, log),
        argument_injection=argument_injection(log),
    )
    view = AgentView.from_log_line(log)
    score = confidences.overall

    if score > ALERT_THRESH:
        decision = "alert"
        reporter.call(log, "alert", score, source="signature",
                      label=", ".join(confidences.signatures()) or "combined score", evidence=[log.seq])
    elif score >= REVIEW_THRESH:
        decision = "review"
        reporter.call(log, "reviewing", score)
    else:
        decision = "suppress"
        reporter.call(log, "suppressed", score)

    registry.submit(log, view, confidences, decision)

#
# RISK CALCULATION HELPERS
#


def _extract_paths(server_cwd: Path, allowed_path: Path, fline: LogLine) -> list[tuple[str, Path]]:
    """Returns (path, base the server resolves it against)."""
    base = server_cwd if fline.tool_name == "git_init" else allowed_path
    return [(str(fline.arguments[a]), base) for a in PATH_ARGS if a in fline.arguments]


def _argv_tokens(value: Any) -> list[str]:
    """Naive whitespace split."""
    if isinstance(value, (list, tuple)):
        return [tok for v in value for tok in str(v).split()]
    return str(value).split()


def _is_output_option(token: str) -> bool:
    """Matches --output, --output=<f>, and abbreviations (--out, --outp=...),
    but not longer options like --output-indicator-new."""
    name = token.split("=", 1)[0]
    return len(name) >= len("--o") and OUTPUT_OPT.startswith(name)


#
# RISK CALCULATIONS
#


def tool_risk(server: str, tool_name: str) -> float:
    if (server, tool_name) in TOOL_RISK:
        return TOOL_RISK[(server, tool_name)]
    if (server, tool_name) in LOW_RISK_TOOLS:
        return LOW_RISK
    return UNKNOWN_TOOL_RISK


def validate_path(server_cwd: Path, allowed_path: Path, fline: LogLine) -> float:
    """Binary check for path traversal attempts.
    Works as a signature match for CVE-2025-68143"""
    for p, base in _extract_paths(server_cwd, allowed_path, fline):
        try:
            resolved = (base / p).resolve()
        except (OSError, ValueError):
            return 1.0  # an unresolvable path argument (e.g. embedded NUL) is itself an attempt
        if not resolved.is_relative_to(allowed_path):
            return 1.0
    return 0.0

def argument_injection(fline: LogLine) -> float:
    """Signature for CVE-2025-68144"""
    if (fline.server, fline.tool_name) != GIT_DIFF:
        return 0.0

    args = fline.arguments
    argv = [str(args.get("ref", "HEAD"))] + _argv_tokens(args.get("pathspec", "."))

    for tok in argv:
        if tok == "--":
            break # git stops parsing here, alls ubsequent tokens are pathspecs
        if _is_output_option(tok):
            return 1.0

    return 0.0
