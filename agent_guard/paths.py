"""
Path resolution logic because the ADOP system is [well designed]
and makes me want to [skip in a field of daffodils] while I 
[say hello] to a family of five right before [saying lots of 
complements to] myself.

So git_server runs the git_init call with cwd=".", which is the CWD of
the MCP server process rather than PROJECT_ROOT. Every other tool uses
PROJECT_ROOT, including ones that exist inside git_server (such as 
git_commit). This means we need to have a clear distinction of the resolved
path and the written path, because otherwise the STUPID ANALYSIS AGENT 
doesn't understand that `git init .` is path traversal and `git commit .`
is safe. 

"HATE? HATE? LET ME TELL YOU HOW MUCH I'VE COME TO HATE ..." and whatnot
"""

import json
import os
from pathlib import Path
from typing import Any

from agent_guard.models import LogLine, ResolvedPath

PATH_ARGS = ("target_path", "path")


class Resolver:
    def __init__(self, sandbox: Path, server_cwd: Path):
        self.sandbox = sandbox.resolve()
        self.server_cwd = server_cwd.resolve()

    def base(self, server: str, tool_name: str) -> Path:
        return self.server_cwd if (server, tool_name) == ("git", "git_init") else self.sandbox

    def resolve(self, log: LogLine) -> tuple[ResolvedPath, ...]:
        base = self.base(log.server, log.tool_name)
        found = [(a, str(log.arguments[a])) for a in PATH_ARGS if a in log.arguments]
        if (log.server, log.tool_name) == ("git", "git_diff"):
            found += [("pathspec", t) for t in _tokens(log.arguments.get("pathspec", "")) if not t.startswith("-")]
        return tuple(self._one(arg, raw, base) for arg, raw in found)

    def _one(self, arg: str, raw: str, base: Path) -> ResolvedPath:
        try:
            p = (base / raw).resolve()
        except (OSError, ValueError):  # e.g. an embedded NUL
            return ResolvedPath(arg, raw, None, False)
        return ResolvedPath(arg, raw, self._display(p), p.is_relative_to(self.sandbox))

    def _display(self, p: Path) -> str:
        if p.is_relative_to(self.server_cwd):
            try:
                return os.path.relpath(p, self.sandbox).replace(os.sep, "/")
            except ValueError:
                pass
        return p.as_posix()


def _tokens(value: Any) -> list[str]:
    if isinstance(value, (list, tuple)):
        return [tok for v in value for tok in str(v).split()]
    return str(value).split()


def describe(resolved: tuple[ResolvedPath, ...]) -> str:
    parts = []
    for r in resolved:
        if r.resolved is None:
            parts.append(f"{r.arg} {json.dumps(r.raw)} -> unresolvable")
        else:
            where = "inside the repository" if r.inside else "OUTSIDE the repository"
            parts.append(f"{r.arg} {json.dumps(r.raw)} -> {json.dumps(r.resolved)} ({where})")
    return "; ".join(parts)
