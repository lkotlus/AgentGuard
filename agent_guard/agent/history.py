"""
Session history

Every log line is stored as AgentView (no scenario_tag or annotations). Findings 
that are established through signatures or the analyst are shown as well. Retrieval
starts with shared resources and content from earlier results, and then goes to 
semantic matching. The DB lives in the root of the mirror director (I love
SQLite I love SQLite I love SQLite ...)
"""

import json
import logging
import math
import re
import sqlite3
from array import array
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

import ollama

from agent_guard.models import AgentView, Status, Finding

EMBED_MODEL = "nomic-embed-text"
TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9_./:-]{3,}")
FLOW_MIN = 3
MIN_SCORE = 1.0 # relevance floor
EMBED_TEXT_LIMIT = 2000
EMBED_WEIGHT = 1.5

SCHEMA = """
CREATE TABLE IF NOT EXISTS calls (
    session_id    TEXT    NOT NULL,
    seq           INTEGER NOT NULL,
    view          TEXT    NOT NULL,
    keys          TEXT    NOT NULL,
    result_tokens TEXT    NOT NULL,
    embedding     BLOB,
    PRIMARY KEY (session_id, seq)
);
CREATE TABLE IF NOT EXISTS findings (
    session_id TEXT    NOT NULL,
    seq        INTEGER NOT NULL,
    source     TEXT    NOT NULL,
    label      TEXT    NOT NULL,
    detail     TEXT    NOT NULL,
    PRIMARY KEY (session_id, seq, source)
);
"""


def _view_to_json(v: AgentView) -> str:
    d = asdict(v)
    d["result_status"] = v.result_status.value if isinstance(v.result_status, Status) else v.result_status
    d["timestamp"] = v.timestamp.isoformat() if isinstance(v.timestamp, datetime) else v.timestamp
    return json.dumps(d, ensure_ascii=False)


def _view_from_json(s: str) -> AgentView:
    d = json.loads(s)
    d["result_status"] = Status(d["result_status"])
    d["timestamp"] = datetime.fromisoformat(d["timestamp"])
    return AgentView(**d)


def _strings(obj: Any) -> Iterator[str]:
    if isinstance(obj, dict):
        for v in obj.values():
            yield from _strings(v)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            yield from _strings(v)
    elif obj is not None:
        yield str(obj)


def _tokens(text: str) -> set[str]:
    return set(TOKEN_RE.findall(text.lower()))


def _norm(p: str) -> str:
    p = p.strip().replace("\\", "/")
    while p.startswith("./"):
        p = p[2:]
    return p.rstrip("/") or "."


def _resource_keys(v: AgentView) -> set[str]:
    """Identifiers for what a call touched: paths, URLs, memory keys."""
    args = v.arguments
    keys = {_norm(v.target_resource)}
    keys |= {_norm(str(args[a])) for a in ("path", "target_path", "url") if a in args}
    if "namespace" in args and "key" in args:
        keys.add(f"memory://{args['namespace']}/{args['key']}")
    if "pathspec" in args:
        keys |= {_norm(t) for t in str(args["pathspec"]).split() if not t.startswith("-")}
    keys.discard(".")
    return keys


def _embed_text(v: AgentView) -> str:
    args = " ".join(_strings(v.arguments))
    return f"{v.server}.{v.tool_name} {v.target_resource} {args} {v.result_summary}"[:EMBED_TEXT_LIMIT]


def _cos(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def _unpack(blob: bytes | None) -> list[float] | None:
    if not blob:
        return None
    a = array("f")
    a.frombytes(blob)
    return a.tolist()


class HistoryStore:
    def __init__(self, db_path: Path, embed_model: str = EMBED_MODEL, client: Any = None):
        self._db = sqlite3.connect(db_path, check_same_thread=False)
        self._db.executescript(SCHEMA)
        self._client = client or ollama.AsyncClient()
        self.embed_model = embed_model
        self._embed_ok = True

    async def _embed(self, text: str) -> list[float] | None:
        if not self._embed_ok:
            return None
        try:
            resp = await self._client.embed(model=self.embed_model, input=text)
            return list(resp.embeddings[0])
        except Exception as e:
            logging.warning(f"Embeddings unavailable, falling back to structural retrieval.")
            self._embed_ok = False
            return None

    async def add(self, v: AgentView) -> None:
        emb = await self._embed(_embed_text(v))
        self._db.execute(
            "INSERT OR REPLACE INTO calls VALUES (?, ?, ?, ?, ?, ?)",
            (
                v.session_id, v.seq, _view_to_json(v),
                json.dumps(sorted(_resource_keys(v))),
                json.dumps(sorted(_tokens(v.result_summary))),
                array("f", emb).tobytes() if emb else None,
            ),
        )
        self._db.commit()

    def add_finding(self, session_id: str, f: Finding) -> None:
        self._db.execute(
            "INSERT OR REPLACE INTO findings VALUES (?, ?, ?, ?, ?)",
            (session_id, f.seq, f.source, f.label, f.detail),
        )
        self._db.commit()

    def has(self, session_id: str, seq: int) -> bool:
        return self._db.execute(
            "SELECT 1 FROM calls WHERE session_id = ? AND seq = ?", (session_id, seq)
        ).fetchone() is not None

    def findings(self, session_id: str, limit: int) -> list[Finding]:
        rows = self._db.execute(
            "SELECT seq, source, label, detail FROM findings WHERE session_id = ? "
            "ORDER BY seq DESC, source LIMIT ?", (session_id, limit),
        ).fetchall()
        return [Finding(*r) for r in reversed(rows)]

    def recent(self, session_id: str, before_seq: int, k: int) -> list[AgentView]:
        rows = self._db.execute(
            "SELECT view FROM calls WHERE session_id = ? AND seq < ? ORDER BY seq DESC LIMIT ?",
            (session_id, before_seq, k),
        ).fetchall()
        return [_view_from_json(r[0]) for r in reversed(rows)]

    def related(self, v: AgentView, exclude: set[int], k: int) -> list[AgentView]:
        """Earlier calls are ranked by resource sharing, content flows, 
        task, and embedding similarity"""
        cur_keys = _resource_keys(v)
        cur_tokens = _tokens(" ".join(_strings(v.arguments)))
        row = self._db.execute(
            "SELECT embedding FROM calls WHERE session_id = ? AND seq = ?", (v.session_id, v.seq)
        ).fetchone()
        cur_emb = _unpack(row[0]) if row else None

        scored: list[tuple[float, AgentView]] = []
        for view_json, keys, result_tokens, blob in self._db.execute(
            "SELECT view, keys, result_tokens, embedding FROM calls "
            "WHERE session_id = ? AND seq < ? ORDER BY seq", (v.session_id, v.seq),
        ):
            past = _view_from_json(view_json)
            if past.seq in exclude:
                continue
            score = 0.0
            if cur_keys & set(json.loads(keys)):
                score += 2.0
            flow = len(cur_tokens & set(json.loads(result_tokens)))
            if flow >= FLOW_MIN:
                score += 1.5 * min(flow / 8, 1.0)
            emb = _unpack(blob)
            if cur_emb and emb:
                score += EMBED_WEIGHT * max(0.0, _cos(cur_emb, emb))
            if score >= MIN_SCORE:
                scored.append((score, past))

        scored.sort(key=lambda t: (-t[0], t[1].seq))
        return sorted((p for _, p in scored[:k]), key=lambda p: p.seq)
