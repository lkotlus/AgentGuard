import time
import logging
import argparse
from pathlib import Path
from watchdog.observers import Observer

from event_handler import AGEventHandler


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

    parser.add_argument("-p", "--path", type=str, required=True, help="Path to the directory you want to watch.")
    parser.add_argument("-a", "--agent-root", type=str, required=True, help="Path to the agent root.")

    args = parser.parse_args()

    if not Path(args.path).is_dir():
        parser.error("Provided path does not exist or is not a directory.")
    if not Path(args.agent_root).is_dir():
        parser.error("Provided agent root does not exist or is not a directory.")

    print_banner(args.path, args.agent_root)

    logging.basicConfig(level=logging.WARNING, format='%(asctime)s - %(message)s', datefmt='%Y-%m-%d %H:%M:%S')
    event_handler = AGEventHandler(args.agent_root)

    observer = Observer()
    observer.schedule(event_handler, args.path, recursive=True)
    observer.start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()

    observer.join()
