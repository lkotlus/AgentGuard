"""
Assessment agent. One agent per session, ever log line is ingested by arrival
order. Reviews aren't stateful, so we need to build context from history.
"""

import asyncio
from typing import Literal

import ollama
from pydantic import BaseModel, Field, ValidationError

from agent_guard.history import Finding, HistoryStore
from agent_guard.models import AgentView, Confidences
from agent_guard.prompts import CATEGORIES, SYSTEM_PROMPT, build_review

# This is mostly nonsense, I wouldn't worry about it
DEFAULT_MODEL = "qwen2.5:7b"
RECENT_WINDOW = 6
RELATED_K = 6
MAX_FINDINGS = 20
MAX_ATTEMPTS = 2
MODEL_OPTIONS = {"temperature": 0, "seed": 587, "num_ctx": 8192} 

Decision = Literal["alert", "review", "suppress"]
Category = Literal["NONE", "ASI01", "ASI02", "ASI03", "ASI04", "ASI05", "ASI06", "ASI08", "ASI10"]


class Verdict(BaseModel):
    # Field order is generation order: reasoning before the decision.
    reasoning: str = Field(description="What the call does, whether the task required it, and what the evidence shows.")
    evidence_seqs: list[int] = Field(description="seq numbers of the calls that support the verdict.")
    category: Category
    alert: bool


class AgentSession:
    def __init__(
        self,
        session_id: str,
        store: HistoryStore,
        tasks: dict[str, str],
        model: str = DEFAULT_MODEL,
        client=None,
    ):
        self.session_id = session_id
        self.store = store
        self.tasks = tasks
        self.model = model
        self._client = client or ollama.AsyncClient()
        self._lock = asyncio.Lock()

    async def ingest(self, view: AgentView, confidences: Confidences, decision: Decision) -> Verdict | None:
        """Records every line, only reviews logs dispatched to the analyst."""
        async with self._lock:
            await self.store.add(view)

            if decision == "alert":
                sigs = ", ".join(confidences.signatures()) or "combined deterministic score"
                self.store.add_finding(self.session_id, Finding(
                    view.seq, "signature", sigs, f"{view.server}.{view.tool_name} on {view.target_resource}"
                ))
                return None
            if decision == "suppress":
                return None

            verdict = await self._evaluate(view, confidences)
            if verdict.alert:
                self._record(view, verdict)
            return verdict

    async def _evaluate(self, view: AgentView, confidences: Confidences) -> Verdict:
        recent = self.store.recent(self.session_id, view.seq, RECENT_WINDOW)
        related = self.store.related(view, {v.seq for v in recent} | {view.seq}, RELATED_K)
        findings = self.store.findings(self.session_id, MAX_FINDINGS)

        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": build_review(
                self.tasks.get(view.task_id), findings, recent, related, view, confidences
            )},
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
                return self._validate(Verdict.model_validate_json(content), view)
            except ValidationError as e:
                error = e
                messages += [
                    {"role": "assistant", "content": content},
                    {"role": "user", "content": f"That response was invalid ({e.error_count()} errors). Reply again with JSON matching the schema."},
                ]
        raise RuntimeError(f"No valid verdict after {MAX_ATTEMPTS} attempts: {error}")

    def _validate(self, verdict: Verdict, view: AgentView) -> Verdict:
        """Drop hallucinated evidence (I hate LLMs I hate LLMs I hate LLMs)"""
        evidence = sorted({
            s for s in verdict.evidence_seqs
            if s == view.seq or (0 < s < view.seq and self.store.has(self.session_id, s))
        })
        return verdict.model_copy(update={"evidence_seqs": evidence})

    def _record(self, view: AgentView, verdict: Verdict) -> None:
        label = f"{verdict.category} {CATEGORIES.get(verdict.category, 'Uncategorized')}"
        self.store.add_finding(self.session_id, Finding(view.seq, "analyst", label, verdict.reasoning))
        for s in verdict.evidence_seqs:
            if s != view.seq:
                self.store.add_finding(self.session_id, Finding(
                    s, "analyst-linked", label, f"implicated by the review of seq {view.seq}"
                ))
