"""
This is where the magic happens. Signature-based results 
get dispatched to agents, which then further evaluate based on
other evidence.
"""

from agent_guard.models import LogLine, AgentView, Confidences
from agent_guard.registry import registry

def dispatch_finding(
    log: LogLine, 
    agent_log: AgentView,
    confidences: Confidences
) -> None:
    """Dispatches to agent."""

    if confidences.overall > 0.8:
        print(f"Anomalous log (high signature match, seq {log.seq}):\n\t{log}\n\t{confidences}\n")
    else:
        registry.dispatch(log, agent_log, confidences)
