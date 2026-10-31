import argparse
import logging
import sys
import time
from pathlib import Path

from watchdog.observers import Observer

from agent_guard.agent.agent import DEFAULT_MODEL
from agent_guard.event_handler import AGEventHandler
from agent_guard.registry import registry
from agent_guard.reporting import LibraryLogHandler, LiveView, PlainView, reporter

MIN_VERSION = (3, 11) # This means 3.11
BANNER = r"""
    _                    _    ____                     _
   / \   __ _  ___ _ __ | |_ / ___|_   _  __ _ _ __ __| |
  / _ \ / _` |/ _ \ '_ \| __| |  _| | | |/ _` | '__/ _` |
 / ___ \ (_| |  __/ | | | |_| |_| | |_| | (_| | | | (_| |
/_/   \_\__, |\___|_| |_|\__|\____|\__,_|\__,_|_|  \__,_|
        |___/
"""


def print_banner(watch_path: Path, agent_root: Path) -> None:
    print(BANNER)
    print(f"  watching : {watch_path}")
    print(f"  sandbox  : {agent_root}")
    print(f"  {'-' * 40}\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="File watching and static analysis script.")
    parser.add_argument("-p", "--path", type=str, required=True,
                        help="Path to the directory you want to watch (typically adop-cyse/corpus/).")
    parser.add_argument("-a", "--agent-root", type=str, required=True,
                        help="Path to the agent root (typically adop-cyse/testbed-repo/).")
    parser.add_argument("-s", "--server-cwd", type=str, default=None,
                        help="Working directory of the MCP server process."
                        "(defaults to parent of agent-root)")
    parser.add_argument("-m", "--mirror-root", type=str, default="./mirror/",
                        help="Directory for log mirrors, AG logs, and the RAG DB.")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="Ollama model for the analyst.")
    parser.add_argument("--plain", action="store_true",
                        help="Disables the TUI.")
    args = parser.parse_args()

    if not Path(args.path).is_dir():
        parser.error("Provided path does not exist or is not a directory.")
    if not Path(args.agent_root).is_dir():
        parser.error("Provided agent root does not exist or is not a directory.")

    mirror_root = Path(args.mirror_root).resolve()
    for protected in (Path(args.path).resolve(), Path(args.agent_root).resolve().parent):
        if mirror_root.is_relative_to(protected):
            parser.error(f"Mirror root must not be inside {protected}; the testbed can write there.")

    plain = args.plain or not sys.stdout.isatty()
    view = PlainView() if plain else LiveView(reporter, watch=args.path, mirror=str(mirror_root), model=args.model)
    if plain:
        print_banner(args.path, args.agent_root)

    logging.basicConfig(level=logging.WARNING, handlers=[LibraryLogHandler()], force=True)

    event_handler = AGEventHandler(args.agent_root, args.path, args.mirror_root, args.server_cwd)
    registry.configure(mirror_root / "history.sqlite3", model=args.model)
    reporter.configure(mirror_root / "agentguard-events.jsonl", view)

    observer = Observer()
    observer.schedule(event_handler, args.path, recursive=True)

    with view:
        event_handler.resume()
        observer.start()
        try:
            while observer.is_alive():
                time.sleep(1)
            # I am HILARIOUS put me on marketing stat
            reporter.critical("File observer stopped. No longer AgentGuarding.")
        except KeyboardInterrupt:
            pass
        finally:
            observer.stop()

    observer.join()
