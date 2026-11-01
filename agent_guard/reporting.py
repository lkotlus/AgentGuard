"""
I swear that this is the CLOSEST I will get to front-end development. Once
we're going for a super cool live-demo or something like that and back-end
is all ready to go, we can have Alex's agent handle some sort of live 
front-end or generated HTML report but I REFUSE SUCH FRIVOLITIES. I have
*standards*.

This whole file is mostly vibe-coded, so please keep that in mind when
casting the due judgement on the general state of things.
"""

import copy
import json
import logging
import threading
import traceback as tb
from collections import deque
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from rich import box
from rich.console import Console, Group
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from agent_guard.agent.prompts import CATEGORIES
from agent_guard.models import (
    Decision,
    Event,
    Level,
    LogLine,
    Row,
    Snapshot,
    Incident
)


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _clean(s: object) -> str:
    """Log fields are attacker-influenced: no control characters (terminal escapes) reach the screen."""
    return "".join(ch if ch.isprintable() else "\ufffd" for ch in " ".join(str(s).split()))


def _clip(s: object, n: int) -> str:
    s = _clean(s)
    return s if len(s) <= n else s[: n - 1] + "…"


def _short(session_id: str, width: int = 14) -> str:
    return session_id if len(session_id) <= width else "…" + session_id[-(width - 1):]


def category_label(category: str | None) -> str:
    return f"{category} {CATEGORIES[category]}" if category in CATEGORIES else "uncategorized"


def verdict_label(r: "Row | Event") -> str:
    if r.decision == "error":
        return "analyst failed"
    if r.source == "signature":
        return f"SIGNATURE {r.label}"
    return category_label(r.label)


class Reporter:
    def __init__(self):
        self._lock = threading.Lock()
        self._path: Path | None = None
        self._view = None
        self._sessions: dict[str, dict[int, Row]] = {}
        self._activity: dict[str, int] = {}
        self._tick = 0
        self._integrity: list[Event] = []
        self._notices: deque[Event] = deque(maxlen=3)
        self._write_failed = False

    def configure(self, events_path: Path, view) -> None:
        self._path = events_path
        self._view = view

    #
    # Producers
    #

    def call(self, log: LogLine, decision: Decision, score: float, *, source: str | None = None,
             label: str | None = None, evidence=(), reasoning: str | None = None) -> None:
        self._emit(Event(
            kind="call", time=_now(), level=Level.CRITICAL if decision in ("alert", "error") else Level.INFO,
            session_id=log.session_id, seq=log.seq, tool=f"{log.server}.{log.tool_name}",
            target=log.target_resource, decision=decision, source=source, score=round(score, 3),
            label=label, evidence=list(evidence), reasoning=reasoning,
        ))

    def integrity(self, path, message: str) -> None:
        self._emit(Event(kind="integrity", time=_now(), level=Level.CRITICAL, target=str(path), message=message))

    def system(self, level: Level | str, message: str, traceback: str | None = None) -> None:
        self._emit(Event(kind="system", time=_now(), level=Level(level), message=message, traceback=traceback))

    #
    # State (Dijkstra was so right)
    #

    def _emit(self, e: Event) -> None:
        with self._lock:
            failure = self._write(e)
            for event in (e, failure) if failure else (e,):
                self._apply(event)
                if self._view:
                    self._view.on_event(event)

    def _write(self, e: Event) -> Event | None:
        """Appends to the event log. A failure is returned as a notice instead of raised,
        so the event is still displayed; it's reported once until writes recover."""
        if not self._path:
            return None
        try:
            with open(self._path, "a", encoding="utf-8") as f:
                f.write(json.dumps(asdict(e), ensure_ascii=False) + "\n")
        except OSError as err:
            if self._write_failed:
                return None
            self._write_failed = True
            return Event(kind="system", time=_now(), level=Level.CRITICAL,
                         message=f"Event log write failed ({err}). Events are still"
                                 f"shown but not recorded to {self._path}.")
        self._write_failed = False
        return None

    def _apply(self, e: Event) -> None:
        if e.kind == "integrity":
            self._integrity.append(e)
            return
        if e.kind == "system":
            self._notices.append(e)
            return

        rows = self._sessions.setdefault(e.session_id, {}) # type: ignore
        self._tick += 1
        self._activity[e.session_id] = self._tick # type: ignore

        row = rows.get(e.seq) or rows.setdefault(  # type: ignore
            e.seq, Row(e.seq, e.tool, e.target, e.score, e.decision) # type: ignore
        )
        row.decision, row.score, row.source, row.label = e.decision, e.score, e.source, e.label # type: ignore
        row.evidence, row.reasoning = e.evidence, e.reasoning
        if e.decision == "alert":
            for s in e.evidence:
                if s != e.seq and s in rows:
                    rows[s].linked_by.add(e.seq) # type: ignore

    def snapshot(self) -> Snapshot:
        with self._lock:
            return Snapshot(
                copy.deepcopy(self._sessions),
                sorted(self._sessions, key=self._activity.__getitem__),
                list(self._integrity),
                list(self._notices),
            )

    #
    # Convenience methods
    #

    def critical(self, message: str) -> None:
        self.system(Level.CRITICAL, message)

    def warning(self, message: str) -> None:
        self.system(Level.WARNING, message)

    def info(self, message: str) -> None:
        self.system(Level.INFO, message)


reporter = Reporter()


class LibraryLogHandler(logging.Handler):
    """All reporting is done through the reporter."""

    def emit(self, record: logging.LogRecord) -> None:
        level = Level.CRITICAL if record.levelno >= logging.ERROR else Level.WARNING
        try:
            message = record.getMessage()
        except (TypeError, ValueError):
            self.handleError(record)
            return
        trace = "".join(tb.format_exception(*record.exc_info)) if record.exc_info else None
        reporter.system(level, f"[{record.name}] {message}", traceback=trace)


def incidents(rows: dict[int, Row]) -> list[Incident]:
    out = []
    for r in sorted(rows.values(), key=lambda r: r.seq):
        if r.decision not in ("alert", "error"):
            continue
        cited = [s for s in r.evidence if s != r.seq and s in rows]
        cites = sorted(s for s in cited if rows[s].decision in ("alert", "error"))
        chain = sorted({r.seq, *(s for s in cited if s not in cites)})
        out.append(Incident(r.seq, chain, cites))
    return out


#
# Views
#


class PlainView:
    """One line per event and fixed columns."""
    def __init__(self):
        self._closed = False

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def on_event(self, e: Event) -> None:
        if self._closed:
            return
        try:
            print(self.format(e), flush=True)
        except BrokenPipeError:
            self._closed = True

    @staticmethod
    def format(e: Event) -> str:
        t = e.time[11:19]
        if e.kind == "integrity":
            return f"{t}  {'INTEGRITY':<14}  {_clean(e.target)}: {_clean(e.message)}"
        if e.kind == "system":
            return f"{t}  {e.level.name.upper():<14}  {_clean(e.message)}"

        head = f"{t}  {_short(e.session_id):<14}  seq {e.seq:>4}  {_clip(e.tool, 26):<26}  {e.decision.upper():<10}" #type: ignore
        if e.decision == "alert" and e.source == "signature":
            tail = f"{verdict_label(e)}  {_clip(e.reasoning or 'target ' + str(e.target), 100)}"
        elif e.decision == "alert":
            evidence = ",".join(map(str, e.evidence)) or "-"
            tail = f"{verdict_label(e)}  evidence {evidence}  \"{_clip(e.reasoning or '', 160)}\""
        elif e.decision == "error":
            tail = f"treated as alert: {_clip(e.reasoning or '', 160)}"
        elif e.decision == "cleared":
            tail = f"score {e.score:.2f}  \"{_clip(e.reasoning or '', 120)}\""
        else:
            tail = f"score {e.score:.2f}  target {_clip(e.target, 60)}"
        return f"{head}  {tail}"


class LiveView:
    """Such a fancy TUI that you'd think I'm a Rust dev."""

    def __init__(self, source: Reporter, *, watch: str, mirror: str, model: str,
                 max_rows: int = 14, max_sessions: int = 2, max_incidents: int = 6,
                 console: Console | None = None):
        self.source = source
        self.watch, self.mirror, self.model = watch, mirror, model
        self.max_rows, self.max_sessions = max_rows, max_sessions
        self.max_incidents = max_incidents
        self._live = Live(
            console=console or Console(), get_renderable=self.render,
            refresh_per_second=4, redirect_stdout=True, redirect_stderr=True,
        )

    def __enter__(self):
        self._live.start()
        return self

    def __exit__(self, *exc):
        self._live.refresh()
        self._live.stop()
        return False

    def on_event(self, e: Event) -> None:
        pass  # Live re-renders from the reporter's state on its own schedule

    def render(self) -> Panel:
        snap = self.source.snapshot()
        found = [(sid, chain) for sid in snap.order for chain in incidents(snap.sessions[sid])]
        body = [self._alerts(snap, found)]
        for sid in reversed(snap.order[-self.max_sessions:]):
            body.append(self._session(sid, snap.sessions[sid])) # type: ignore
        return Panel(
            Group(*body),
            title=Text.assemble(("AgentGuard", "bold"), f" · watching {self.watch} · mirror {self.mirror} · analyst {self.model}"),
            title_align="left",
            subtitle=self._footer(snap, found),
            subtitle_align="left",
            box=box.ROUNDED,
        )

    def _alerts(self, snap: Snapshot, found: list[tuple[str, Incident]]) -> Panel:
        grid = Table.grid(expand=True)
        grid.add_column(ratio=1)

        for e in snap.integrity:
            grid.add_row(Text.assemble(
                (" TAMPER ", "bold white on red"), "  ",
                (f"{e.time[11:19]}  {_clean(e.target)}: {_clean(e.message)}", "red"),
            ))

        shown = found[-self.max_incidents:]
        if len(found) > len(shown):
            grid.add_row(Text(f"… {len(found) - len(shown)} earlier incidents", style="dim"))

        for sid, inc in shown:
            r = snap.sessions[sid][inc.seq]
            chain_text = " → ".join(map(str, inc.chain))
            line = Text.assemble(
                ("■ ", "bold red"), (f"{_short(sid)}  ", "dim"),
                (f"seq {chain_text}", "bold"), "   ", (verdict_label(r), "red"),
            )
            if inc.cites:
                line.append(f"   cites {', '.join(map(str, inc.cites))}", style="dim red")
            grid.add_row(line)

            detail = _clip(r.reasoning, 100) if r.reasoning else f"→ {_clip(r.target, 70)}"
            grid.add_row(Text(f"   {r.tool}: {detail}", style="dim"))

        alerting = bool(snap.integrity or found)
        return Panel(
            grid if alerting else Text("No alerts", style="green"),
            title="Alerts", title_align="left", box=box.SQUARE,
            border_style="red" if alerting else "green",
        )

    def _session(self, sid: str, rows: dict[int, Row]) -> Table:
        t = Table(box=box.SIMPLE_HEAD, expand=True, pad_edge=False,
                  title=Text(sid, style="bold"), title_justify="left")
        t.add_column("seq", justify="right", no_wrap=True, width=7)
        t.add_column("tool", no_wrap=True, overflow="ellipsis", max_width=26)
        t.add_column("target", ratio=1, min_width=24, no_wrap=True, overflow="ellipsis")
        t.add_column("score", justify="right", no_wrap=True, width=5)
        t.add_column("verdict", no_wrap=True, overflow="ellipsis", max_width=32)

        lines = self._collapse(rows)
        hidden = max(0, len(lines) - self.max_rows)
        if hidden:
            t.add_row("", Text(f"… {hidden} earlier rows", style="dim"), "", "", "")
        for item in lines[hidden:]:
            if isinstance(item, tuple):
                first, last, n = item
                t.add_row(Text(f"{first}–{last}", style="dim"), Text(f"{n} suppressed", style="dim"),
                          "", "", Text("·", style="dim"))
                continue
            r = item
            style = "red" if r.decision in ("alert", "error") else ("dim" if r.decision == "suppressed" else "")
            t.add_row(str(r.seq), _clip(r.tool, 26), _clean(r.target), f"{r.score:.2f}", self._verdict(r), style=style)
        return t

    @staticmethod
    def _collapse(rows: dict[int, Row]) -> list:
        """Runs of two or more plain suppressed calls collapse into one row."""
        out: list = []
        run: list[Row] = []

        def flush():
            if len(run) == 1:
                out.append(run[0])
            elif run:
                out.append((run[0].seq, run[-1].seq, len(run)))
            run.clear()

        for r in sorted(rows.values(), key=lambda r: r.seq):
            if r.decision == "suppressed" and not r.linked_by:
                run.append(r)
            else:
                flush()
                out.append(r)
        flush()
        return out

    @staticmethod
    def _verdict(r: Row) -> Text:
        if r.linked_by and r.decision not in ("alert", "error"):
            return Text(f"linked → {', '.join(map(str, sorted(r.linked_by)))}", style="red")
        return {
            "suppressed": Text("·", style="dim"),
            "reviewing": Text("reviewing…", style="yellow"),
            "cleared": Text("cleared", style="green"),
            "alert": Text(verdict_label(r), style="bold red"),
            "error": Text("analyst failed", style="bold magenta"),
        }[r.decision]

    def _footer(self, snap: Snapshot, found: list) -> Text:
        rows = [r for s in snap.sessions.values() for r in s.values()]
        n = lambda d: sum(r.decision == d for r in rows)
        footer = Text(
            f" {len(rows)} calls · {n('suppressed')} suppressed · {n('reviewing')} reviewing · "
            f"{len(found)} incidents · {len(snap.integrity)} tamper "
        )
        if snap.notices:
            note = snap.notices[-1]
            footer.append(f"· {note.level}: {_clip(note.message, 80)} ",
                          style="yellow" if note.level == "warning" else "bold red")
        return footer
