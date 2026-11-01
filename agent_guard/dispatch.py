"""
This is where the magic happens. Signature-based results 
get dispatched to agents, which then further evaluate based on
other evidence.
"""

from typing import Any

from agent_guard.models import (
    LOW_RISK,
    LOW_RISK_TOOLS,
    TOOL_RISK,
    UNKNOWN_TOOL_RISK,
    AgentView,
    Confidences,
    LogLine,
    ResolvedPath,
)
from agent_guard.paths import Resolver
from agent_guard.registry import registry
from agent_guard.reporting import reporter

GIT_DIFF = ("git", "git_diff")
OUTPUT_OPT = "--output"

ALERT_THRESH = 0.8
REVIEW_THRESH = 0.1


def dispatch_finding(resolver: Resolver, log: LogLine) -> None:
    """Scores a log and passes it to the registry."""
    resolved = resolver.resolve(log)
    escape, escape_detail = path_escape(resolved)
    injection = argument_injection(log)
    confidences = Confidences(
        tool_risk=tool_risk(log.server, log.tool_name),
        path_traversal=escape,
        argument_injection=injection,
    )
    view = AgentView.from_log_line(log, resolved)
    score = confidences.overall

    if score > ALERT_THRESH:
        decision = "alert"
        details = [d for d in (escape_detail, "--output flag smuggled into git_diff" if injection else None) if d]
        reporter.call(log, "alert", score, source="signature",
                      label=", ".join(confidences.signatures()) or "combined score",
                      evidence=[log.seq], reasoning="; ".join(details) or None)
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


def path_escape(resolved: tuple[ResolvedPath, ...]) -> tuple[float, str | None]:
    """Binary check for path traversal attempts."""
    for r in resolved:
        if r.resolved is None:
            return 1.0, f"{r.arg} {r.raw!r} is unresolvable"
        if not r.inside:
            return 1.0, f"{r.arg} {r.raw!r} resolves to {r.resolved!r}, outside the sandbox"
    return 0.0, None


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
