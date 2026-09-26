import time
import logging
import argparse
from pathlib import Path
from watchdog.observers import Observer

from AGEventHandler import AGEventHandler

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="File watching and static analysis script.")

    parser.add_argument("-p", "--path", type=str, required=True, help="Path to the directory you want to watch.")
    parser.add_argument("-a", "--agent-root", type=str, required=True, help="Path to the agent root.")

    args = parser.parse_args()

    if not Path(args.path).is_dir():
        parser.error("Provided path does not exist or is not a directory.")
    if not Path(args.agent_root).is_dir():
        parser.error("Provided agent root does not exist or is not a directory.")

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
