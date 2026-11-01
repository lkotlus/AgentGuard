"""
Session registry! We need to map session IDs to agents.
"""

import asyncio
import concurrent.futures
import sqlite3
import threading
from functools import partial
from pathlib import Path

import httpx
import ollama

from agent_guard.agent.agent import DEFAULT_MODEL, AgentSession, AnalystError, Decision
from agent_guard.agent.history import HistoryStore
from agent_guard.models import AgentView, Confidences, LogLine
from agent_guard.reporting import reporter

MODEL_ERRORS = (AnalystError, ollama.ResponseError, ConnectionError, httpx.TransportError)


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
        future = asyncio.run_coroutine_threadsafe(
            session.ingest(view, log.task_id, confidences, decision),
            self._loop
        )
        future.add_done_callback(partial(self._handle_result, log, decision, confidences.overall))  # type: ignore

    def _handle_result(self, log: LogLine, decision: Decision, score: float, future) -> None:
        try:
            verdict = future.result()
        except concurrent.futures.CancelledError:
            self._unjudged(log, decision, score, "processing was cancelled (AgentGuard shutting down)")
            return
        except MODEL_ERRORS as e:
            self._unjudged(log, decision, score, f"analyst unavailable: {type(e).__name__}: {e}")
            return
        except sqlite3.Error as e:
            self._unjudged(log, decision, score, f"session history unavailable: {e}")
            return

        if verdict is None:
            return
        if verdict.alert:
            reporter.call(log, "alert", score, source="analyst", label=verdict.category,
                          evidence=verdict.evidence_seqs, reasoning=verdict.reasoning)
        else:
            reporter.call(log, "cleared", score, source="analyst", reasoning=verdict.reasoning)

    @staticmethod
    def _unjudged(log: LogLine, decision: Decision, score: float, why: str) -> None:
        if decision == "review":
            reporter.call(log, "error", score, source="analyst", reasoning=why)
        else:
            reporter.warning(f"seq {log.seq} of {log.session_id} not recorded in history: {why}")


registry = SessionRegistry()
