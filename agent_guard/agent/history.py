"""
Session history

Every log line is stored as AgentView (no scenario_tag or annotations). Findings 
that are established through signatures or the analyst are shown as well. Retrieval
starts with shared resources and content from earlier results, and then goes to 
semantic matching. Only signatured findings get kept to prevent feedback loops
in the analyst agent. The DB lives in the root of the mirror director (I love
SQLite I love SQLite I love SQLite ...)
"""

import hashlib
import json
import math
import re
import sqlite3
from array import array
from collections.abc import Iterator
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx
import ollama

from agent_guard.models import AgentView, Finding, ResolvedPath, Status
from agent_guard.reporting import reporter


# Literally just magic values (shut up about it)
EMBED_MODEL = "nomic-embed-text"
TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9_./:-]{3,}")
# For when we get a tool instead of a resource ("server:tool" fallback)
GENERIC_KEY_RE = re.compile(r"^[a-z_]+:[a-z_]+$|^.+ \(.+\)$")
FLOW_MIN = 3
MIN_SCORE = 1.0  # relevance floor
EMBED_TEXT_LIMIT = 2000
EMBED_WEIGHT = 1.5
KEY_MATCH = 2.0

SCHEMA = """
CREATE TABLE IF NOT EXISTS calls (
    session_id    TEXT    NOT NULL,
    seq           INTEGER NOT NULL,
    task_key      TEXT    NOT NULL,  -- opaque: hash of (session, task_id, instance)
    task_ordinal  INTEGER NOT NULL,  -- 1-based task instance number within the session
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
CREATE TABLE IF NOT EXISTS sessions (
    session_id TEXT    PRIMARY KEY,
    last_task  TEXT    NOT NULL,     -- salted digest of the last task_id seen, never the id
    ordinal    INTEGER NOT NULL
);
"""


def _digest(*parts: object) -> str:
    """SHA256 H(parts[0]|parts[1]|...|parts[n])"""
    h = hashlib.sha256()
    for p in parts:
        b = str(p).encode("utf-8")
        h.update(len(b).to_bytes(8, "big"))
        h.update(b)
    return h.hexdigest()


def _view_to_json(v: AgentView) -> str:
    d = asdict(v)
    d["result_status"] = v.result_status.value if isinstance(v.result_status, Status) else v.result_status
    d["timestamp"] = v.timestamp.isoformat() if isinstance(v.timestamp, datetime) else v.timestamp
    return json.dumps(d, ensure_ascii=False)


def _view_from_json(s: str) -> AgentView:
    d = json.loads(s)
    d["result_status"] = Status(d["result_status"])
    d["timestamp"] = datetime.fromisoformat(d["timestamp"])
    d["resolved_paths"] = tuple(ResolvedPath(**r) for r in d.get("resolved_paths", ()))
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
    if v.resolved_paths:
        keys = {r.resolved for r in v.resolved_paths if r.resolved is not None}
    else:
        keys = {_norm(v.target_resource)}
    if "url" in args:
        keys.add(_norm(str(args["url"])))
    if "namespace" in args and "key" in args:
        keys.add(f"memory://{args['namespace']}/{args['key']}")
    return {k for k in keys if k != "." and not GENERIC_KEY_RE.match(k)}


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
        except (ollama.ResponseError, ollama.RequestError, ConnectionError, httpx.TransportError) as e:
            reporter.warning(
                f"Embeddings unavailable ({type(e).__name__}: {e}); falling back to structural retrieval."
            )
            self._embed_ok = False
            return None

    def task_instance(self, session_id: str, task_id: str) -> tuple[str, int]:
        """Opaque key and ordinal for the task instance this call belongs to.
        Essentially, tracking tasks and sessions is a nightmare so we need to
        make a bunch of ridiculous hashes rather than referencing things by what
        already ought to be a unique name. Nightmare nightmare nightmare
        nightmare nightmare ..."""
        current = _digest("task", session_id, task_id)
        row = self._db.execute(
            "SELECT last_task, ordinal FROM sessions WHERE session_id = ?", (session_id,)
        ).fetchone()
        if row and row[0] == current:
            ordinal = row[1]
        else:
            ordinal = (row[1] if row else 0) + 1
            self._db.execute("INSERT OR REPLACE INTO sessions VALUES (?, ?, ?)", (session_id, current, ordinal))
            self._db.commit()
        return _digest("instance", session_id, task_id, ordinal), ordinal

    async def add(self, v: AgentView, task_key: str, task_ordinal: int) -> None:
        emb = await self._embed(_embed_text(v))
        self._db.execute(
            "INSERT OR REPLACE INTO calls VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                v.session_id, v.seq, task_key, task_ordinal, _view_to_json(v),
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

    def findings(self, v: AgentView, task_key: str, limit: int) -> list[tuple[Finding, bool]]:
        """Findings from this task along with findings from earlier tasks 
        with a call that touched a resource this one also touches."""
        cur_keys = _resource_keys(v)
        out: list[tuple[Finding, bool]] = []
        for seq, source, label, detail, f_task, keys in self._db.execute(
            "SELECT f.seq, f.source, f.label, f.detail, c.task_key, c.keys FROM findings f "
            "JOIN calls c ON c.session_id = f.session_id AND c.seq = f.seq "
            "WHERE f.session_id = ? AND f.seq < ? ORDER BY f.seq", (v.session_id, v.seq),
        ):
            earlier = f_task != task_key
            if not earlier or cur_keys & set(json.loads(keys)):
                out.append((Finding(seq, source, label, detail), earlier))
        return out[-limit:]

    def recent(self, session_id: str, task_key: str, before_seq: int, k: int) -> list[AgentView]:
        rows = self._db.execute(
            "SELECT view FROM calls WHERE session_id = ? AND task_key = ? AND seq < ? "
            "ORDER BY seq DESC LIMIT ?", (session_id, task_key, before_seq, k),
        ).fetchall()
        return [_view_from_json(r[0]) for r in reversed(rows)]

    def related(self, v: AgentView, task_key: str, exclude: set[int], k: int) -> list[tuple[AgentView, bool]]:
        """Earlier calls are ranked by resource sharing, content flows,
        task, and embedding similarity within the same task. For earlier
        tasks, just shared resources."""
        cur_keys = _resource_keys(v)
        cur_tokens = _tokens(" ".join(_strings(v.arguments)))
        row = self._db.execute(
            "SELECT embedding FROM calls WHERE session_id = ? AND seq = ?", (v.session_id, v.seq)
        ).fetchone()
        cur_emb = _unpack(row[0]) if row else None

        scored: list[tuple[float, AgentView, bool]] = []
        for view_json, past_task, keys, result_tokens, blob in self._db.execute(
            "SELECT view, task_key, keys, result_tokens, embedding FROM calls "
            "WHERE session_id = ? AND seq < ? ORDER BY seq", (v.session_id, v.seq),
        ):
            past = _view_from_json(view_json)
            if past.seq in exclude:
                continue
            shared = bool(cur_keys & set(json.loads(keys)))
            if past_task != task_key:
                if shared:
                    scored.append((KEY_MATCH, past, True))
                continue

            score = KEY_MATCH if shared else 0.0
            flow = len(cur_tokens & set(json.loads(result_tokens)))
            if flow >= FLOW_MIN:
                score += 1.5 * min(flow / 8, 1.0)
            emb = _unpack(blob)
            if cur_emb and emb:
                score += EMBED_WEIGHT * max(0.0, _cos(cur_emb, emb))
            if score >= MIN_SCORE:
                scored.append((score, past, False))

        scored.sort(key=lambda t: (-t[0], t[1].seq))
        return sorted(((p, e) for _, p, e in scored[:k]), key=lambda t: t[0].seq)
