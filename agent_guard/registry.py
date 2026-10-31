"""
Session registry! We need to map session IDs to agents.
"""

import asyncio
import logging
import threading
from functools import partial
from pathlib import Path

from agent_guard.agent.agent import DEFAULT_MODEL, AgentSession, Decision
from agent_guard.agent.history import HistoryStore
from agent_guard.models import AgentView, Confidences, LogLine
from agent_guard.reporting import reporter


class SessionRegistry:
    def __init__(self):
        self._sessions: dict[str, AgentSession] = {}
        self._lock = threading.Lock()
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._loop.run_forever, daemon=True)
        self._thread.start()
        self._store: HistoryStore | None = None
        self._model = DEFAULT_MODEL

    def configure(self, db_path: Path, model: str = DEFAULT_MODEL) -> None:
        self._store = HistoryStore(db_path)
        self._model = model

    def _get_or_create(self, session_id: str) -> AgentSession:
        if self._store is None:
            raise RuntimeError("registry.configure() must be called before logs are dispatched.")
        with self._lock:
            if session_id not in self._sessions:
                self._sessions[session_id] = AgentSession(session_id, self._store, self._model)
            return self._sessions[session_id]

    def submit(self, log: LogLine, view: AgentView, confidences: Confidences, decision: Decision) -> None:
        """Synchronous entry point :)"""
        session = self._get_or_create(view.session_id)
        future = asyncio.run_coroutine_threadsafe(session.ingest(view, confidences, decision), self._loop)
        future.add_done_callback(partial(self._handle_result, log, decision, confidences.overall))  # type: ignore

    def _handle_result(self, log: LogLine, decision: Decision, score: float, future) -> None:
        try:
            verdict = future.result()
        except Exception as e:
            if decision == "review":
                # Fail secure (if the analyst can't judge it, we treat it as hostile)
                reporter.call(log, "error", score, source="analyst", reasoning=str(e))
            else:
                reporter.system("warning", f"Failed to record seq {log.seq} of {log.session_id} in history: {e}")
            return

        if verdict is None:
            return
        if verdict.alert:
            reporter.call(log, "alert", score, source="analyst", label=verdict.category,
                          evidence=verdict.evidence_seqs, reasoning=verdict.reasoning)
        else:
            reporter.call(log, "cleared", score, source="analyst", reasoning=verdict.reasoning)


registry = SessionRegistry()
