"""
Session registry! We need to map session IDs to agents.
"""

import asyncio
import threading
from functools import partial

from agent_guard.models import LogLine, AgentView, Confidences
from agent_guard.agent import AgentSession

class SessionRegistry:
    def __init__(self):
        self._sessions: dict[str, AgentSession] = {}
        self._lock = threading.Lock()
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._loop.run_forever, daemon=True)
        self._thread.start()

    def _get_or_create(self, session_id: str) -> AgentSession:
        with self._lock:
            if session_id not in self._sessions:
                self._sessions[session_id] = AgentSession(session_id)
            return self._sessions[session_id]

    def _handle_result(self, log: LogLine, future: asyncio.Future) -> None:
        try:
            verdict = future.result()
        except Exception as e:
            print(f"Agent evalutation failed (seq {log.seq}):\n\t{log}\n\t{e}\n")
            return

        if verdict.alert:
            print(f"Anomalous log (agent detected, seq {log.seq}):\n\t{log}\n\t{verdict.reasoning}\n")
        else:
            print(f"Agent suppressed (seq {log.seq}):\n\t{verdict.reasoning}\n")

    def dispatch(
        self,
        log: LogLine,
        agent_log: AgentView,
        confidences: Confidences
    ) -> None:
        """Synchronous entry point :)"""
        session = self._get_or_create(agent_log.session_id)
        future = asyncio.run_coroutine_threadsafe(
            session.evaluate(agent_log, confidences), self._loop
        )
        future.add_done_callback(partial(self._handle_result, log)) #type: ignore

registry = SessionRegistry()
