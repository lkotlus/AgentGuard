import sys
import time
import logging
import argparse
from pathlib import Path
from watchdog.observers import Observer

from agent_guard.agent.agent import DEFAULT_MODEL
from agent_guard.event_handler import AGEventHandler
from agent_guard.registry import registry


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
    if sys.version_info <= MIN_VERSION:
        raise RuntimeError(f"AgentGuard requires Python {MIN_VERSION[0]}.{MIN_VERSION[1]} or greater."
                           f"You are currently using version: {sys.version.split()[0]}.")

    parser = argparse.ArgumentParser(description="File watching and static analysis script.")

    parser.add_argument("--path", type=str, required=True,
                        help="Path to the directory you want to watch (typically adop-cyse/corpus/).")
    parser.add_argument("--agent-root", type=str, required=True,
                        help="Path to the agent root (typically adop-cyse/testbed-repo/).")
    parser.add_argument("--server-cwd", type=str, default=None,
                        help="Working directory of the MCP server process"
                        "(defaults to parent of agent-root.)")
    parser.add_argument("--mirror-root", type=str, default="./mirror/",
                        help="AgentGuard directory for verified log mirrors.")
    parser.add_argument("--model", type=str, default=DEFAULT_MODEL,
                        help="Local model for the assessment agent.")

    args = parser.parse_args()

    if not Path(args.path).is_dir():
        parser.error("Provided path does not exist or is not a directory.")
    if not Path(args.agent_root).is_dir():
        parser.error("Provided agent root does not exist or is not a directory.")

    print_banner(args.path, args.agent_root)

    mirror_root = Path(args.mirror_root).resolve()
    for protected in (Path(args.path).resolve(), Path(args.agent_root).resolve().parent):
        if mirror_root.is_relative_to(protected):
            parser.error(f"Mirror root must not be inside {protected}; the testbed can write there.")

    event_handler = AGEventHandler(args.agent_root, args.path, args.mirror_root, args.server_cwd)
    registry.configure(mirror_root / "history.sqlite3", model=args.model)
    event_handler.resume()

    observer = Observer()
    observer.schedule(event_handler, args.path, recursive=True)
    observer.start()

    try:
        while observer.is_alive():
            time.sleep(1)
        logging.critical("File observer died! AgentGuard is no longer monitoring.")
    except KeyboardInterrupt:
        observer.stop()

    observer.join()
