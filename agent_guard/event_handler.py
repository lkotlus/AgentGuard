"""
AgentGuard Event Handler
"""

import os
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from watchdog.events import (
    FileSystemEventHandler,
    FileCreatedEvent,
    FileModifiedEvent,
    FileMovedEvent,
    FileDeletedEvent,
)

from agent_guard.models import LogLine, TrackedFile
from agent_guard.dispatch import dispatch_finding

LOG_SUFFIX = ".jsonl"
CHUNK = 1 << 16
NONCONFORMING = (json.JSONDecodeError, TypeError, KeyError, ValueError)

def _end_of_last_line(f, size: int) -> int:
    """Offset just past the last newline in an open binary file of `size` bytes."""
    pos = size
    while pos > 0:
        start = max(0, pos - CHUNK)
        f.seek(start)
        i = f.read(pos - start).rfind(b"\n")
        if i != -1:
            return start + i + 1
        pos = start
    return 0


def _last_line(f, size: int) -> tuple[int, bytes]:
    """(start offset, raw bytes incl. newline) of the last non-blank line in a file of complete lines."""
    window = CHUNK
    while True:
        start = max(0, size - window)
        f.seek(start)
        buf = f.read(size - start)
        content = buf.rstrip(b"\r\n")
        nl = content.rfind(b"\n")
        if (not content or nl == -1) and start > 0:
            window *= 2
            continue
        if not content:
            return 0, b""
        line_start = nl + 1
        line_end = buf.index(b"\n", len(content)) + 1
        return start + line_start, buf[line_start:line_end]


class AGEventHandler(FileSystemEventHandler):
    def __init__(self, allowed_path: str, watch_root: str, mirror_root: str, server_cwd: str | None = None):
        super().__init__()
        self.allowed_path = Path(allowed_path).resolve()
        self.watch_root = Path(watch_root).resolve()
        self.mirror_root = Path(mirror_root).resolve()
        self.server_cwd = Path(server_cwd).resolve() if server_cwd else self.allowed_path.parent
        self.files: dict[Path, TrackedFile] = {}
        self.mirror_root.mkdir(parents=True, exist_ok=True, mode=0o700)

    @staticmethod
    def _is_log(path: str | Path) -> bool:
        return Path(path).suffix == LOG_SUFFIX

    def _track(self, fpath: Path) -> TrackedFile:
        st = self.files.get(fpath)
        if st is None:
            mirror = self.mirror_root / fpath.relative_to(self.watch_root)
            mirror.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            st = self.files[fpath] = TrackedFile(mirror=mirror)
        return st

    @staticmethod
    def _tail_intact(f, st: TrackedFile) -> bool:
        if not st.tail:
            return True
        f.seek(st.tail_start)
        return f.read(len(st.tail)) == st.tail

    @staticmethod
    def _rebaseline(f, st: TrackedFile, size: int) -> None:
        st.offset = _end_of_last_line(f, size)
        st.tail, st.tail_start = b"", 0

    @staticmethod
    def _report_tampering(fpath: Path, st: TrackedFile, how: str) -> None:
        logging.critical(
            f"LOG TAMPERING: {fpath} {how}. Last verified copy: {st.mirror}. "
            f"Stop the agent and review the session."
        )

    def read_file(self, fpath: Path) -> list[LogLine]:
        """Mirrors and returns all new complete lines."""
        st = self._track(fpath)

        with open(fpath, "rb") as f:
            size = os.fstat(f.fileno()).st_size
            if size < st.offset or not self._tail_intact(f, st):
                self._report_tampering(fpath, st, "changed after it was read")
                self._rebaseline(f, st, size)
            f.seek(st.offset)
            new = f.read()

        end = new.rfind(b"\n")
        if end == -1:
            return []

        parsed = []
        with open(st.mirror, "ab") as m:
            for part in new[:end].split(b"\n"):
                raw = part + b"\n"
                m.write(raw)
                line = part.rstrip(b"\r")
                if line:
                    st.tail, st.tail_start = raw, st.offset
                    try:
                        parsed.append(LogLine.from_dict(json.loads(line)))
                    except NONCONFORMING as e:
                        logging.warning(f"Non-conforming line in {fpath} at byte {st.offset}: {e}")
                st.offset += len(raw)
            m.flush()
            os.fsync(m.fileno())

        return parsed

    def resume(self) -> None:
        """Call before starting the observer to verify existing logs."""
        for fpath in sorted(self.watch_root.rglob(f"*{LOG_SUFFIX}")):
            fpath = fpath.resolve()
            st = self._track(fpath)
            if st.mirror.exists():
                self._verify_against_mirror(fpath, st)
            self._process(fpath)

    def _verify_against_mirror(self, fpath: Path, st: TrackedFile) -> None:
        with open(fpath, "rb") as src, open(st.mirror, "rb") as mir:
            while m := mir.read(CHUNK):
                if src.read(len(m)) != m:
                    self._report_tampering(
                        fpath,
                        st,
                        "differs from its mirror (modified while AgentGuard was offline)"
                    )
                    self._rebaseline(src, st, os.fstat(src.fileno()).st_size)
                    return
                st.offset += len(m)
            st.tail_start, st.tail = _last_line(mir, st.offset)

    def _process(self, fpath: Path) -> None:
        try:
            flines = self.read_file(fpath)
        except FileNotFoundError:
            return

        for fline in flines:
            print(f"Received a new log from {fline.session_id} (seq {fline.seq})\n")
            dispatch_finding(self.server_cwd, self.allowed_path, fline)

    def on_created(self, event):
        if isinstance(event, FileCreatedEvent) and self._is_log(str(event.src_path)):
            self._process(Path(str(event.src_path)).resolve())

    def on_modified(self, event):
        if isinstance(event, FileModifiedEvent) and self._is_log(str(event.src_path)):
            self._process(Path(str(event.src_path)).resolve())

    def on_moved(self, event):
        if not isinstance(event, FileMovedEvent):
            return
        src, dest = Path(str(event.src_path)).resolve(), Path(str(event.dest_path)).resolve()
        if src in self.files:
            self._report_tampering(src, self.files.pop(src), f"was moved to {dest}")
        if self._is_log(dest):
            self._process(dest)

    def on_deleted(self, event):
        if isinstance(event, FileDeletedEvent):
            p = Path(str(event.src_path)).resolve()
            if p in self.files:
                self._report_tampering(p, self.files.pop(p), "was deleted")
