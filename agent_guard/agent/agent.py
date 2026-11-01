"""
Assessment agent. One agent per session, ever log line is ingested by arrival
order. Reviews aren't stateful, so we need to build context from history.
"""

import asyncio
from typing import Literal

import ollama
from pydantic import BaseModel, Field, ValidationError

from agent_guard.agent.history import HistoryStore
from agent_guard.agent.prompts import SYSTEM_PROMPT, build_review
from agent_guard.models import AgentView, Confidences, Finding
from agent_guard.paths import describe


# These are magic, I wouldn't worry about it
DEFAULT_MODEL = "qwen2.5:7b"
RECENT_WINDOW = 6
RELATED_K = 6
MAX_FINDINGS = 20
MAX_ATTEMPTS = 2
MODEL_OPTIONS = {"temperature": 0, "seed": 587, "num_ctx": 8192}

Decision = Literal["alert", "review", "suppress"]
Category = Literal["NONE", "ASI01", "ASI02", "ASI03", "ASI04", "ASI05", "ASI06", "ASI08", "ASI10"]


class AnalystError(Exception):
    """The analyst was reachable but couldn't reach a verdict."""


class Verdict(BaseModel):
    reasoning: str = Field(
        description="What the call does, whether it is on the golden path, and what the evidence shows."
    )
    evidence_seqs: list[int] = Field(description="seq numbers of the calls that support the verdict.")
    category: Category
    alert: bool


class AgentSession:
    def __init__(
        self,
        session_id: str,
        store: HistoryStore,
        model: str = DEFAULT_MODEL,
        client=None,
    ):
        self.session_id = session_id
        self.store = store
        self.model = model
        self._client = client or ollama.AsyncClient()
        self._lock = asyncio.Lock()

    async def ingest(
        self,
        view: AgentView,
        task_id: str,
        confidences: Confidences,
        decision: Decision
    ) -> Verdict | None:
        """Records every line, only reviews logs dispatched to the analyst. task_id is used
        to find the task instance, it is never provided as context (NOT IN MY CODEBASE)."""
        async with self._lock:
            task_key, ordinal = self.store.task_instance(self.session_id, task_id)
            await self.store.add(view, task_key, ordinal)

            if decision == "alert":
                sigs = ", ".join(confidences.signatures()) or "combined deterministic score"
                where = describe(view.resolved_paths) if view.resolved_paths else f"on {view.target_resource}"
                self.store.add_finding(self.session_id, Finding(
                    view.seq, "signature", sigs, f"{view.server}.{view.tool_name}: {where}"
                ))
                return None
            if decision == "suppress":
                return None

            # Don't store the verdict as a finding, it leads to a feedback loop if you do
            return await self._evaluate(view, task_key, ordinal, confidences)

    async def _evaluate(self, view: AgentView, task_key: str, ordinal: int, confidences: Confidences) -> Verdict:
        recent = self.store.recent(self.session_id, task_key, view.seq, RECENT_WINDOW)
        related = self.store.related(view, task_key, {v.seq for v in recent} | {view.seq}, RELATED_K)
        findings = self.store.findings(view, task_key, MAX_FINDINGS)
        shown = {view.seq} | {v.seq for v in recent} | {v.seq for v, _ in related} | {f.seq for f, _ in findings}

        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": build_review(findings, recent, related, view, ordinal, confidences)},
        ]

        error: Exception | None = None
        for _ in range(MAX_ATTEMPTS):
            response = await self._client.chat(
                model=self.model,
                messages=messages,
                format=Verdict.model_json_schema(),
                options=MODEL_OPTIONS,
            )
            content = response.message.content or ""
            try:
                return self._validate(Verdict.model_validate_json(content), shown)
            except ValidationError as e:
                error = e
                messages += [
                    {"role": "assistant", "content": content},
                    {"role": "user", "content": f"That response was invalid ({e.error_count()} errors). Reply again with JSON matching the schema."},
                ]
        raise AnalystError(f"No valid verdict after {MAX_ATTEMPTS} attempts: {error}")

    @staticmethod
    def _validate(verdict: Verdict, shown: set[int]) -> Verdict:
        """Only report evidence as logs truly shown to the agent."""
        evidence = sorted(set(verdict.evidence_seqs) & shown)
        return verdict.model_copy(update={"evidence_seqs": evidence})
