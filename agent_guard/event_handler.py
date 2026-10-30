"""
AgentGuard Event Handler

Upon an update to any file within a given corpus directory,
the event handler will get the additions to the file. It then
determines which portion(s) of the additon(s) is/are valid jsonl.
The valid lines are analyzed before being sent to the agent.
"""

import json
import logging
import hashlib
import os
from pathlib import Path
from watchdog.events import FileModifiedEvent, LoggingEventHandler

from agent_guard.models import LogLine, AgentView, Confidences
from agent_guard.dispatch import dispatch_finding

PATH_ARGS = ["target_path", "path"]

class AGEventHandler(LoggingEventHandler):
    def __init__(self, allowed_path: str):
        self.fcontents = {}
        self.allowed_path = Path(allowed_path).resolve()

        super().__init__()

    def read_file(self, fpath: bytes | str) -> list[LogLine]:
        """Returns a list of all new valid lines"""
        with open(fpath, "r", encoding="utf-8") as f:
            contents = f.read()

        prior = self.fcontents.setdefault(fpath, "")
        if not contents.startswith(prior):
            logging.critical(f"FILE CONTENTS OF {fpath} ILLEGALLY MODIFIED!")
            os._exit(1)

        parsed_lines = []
        for line in contents[len(prior):].split("\n")[:-1]:  # drop trailing unterminated line
            if line:
                try:
                    parsed_lines.append(LogLine.from_dict(json.loads(line)))
                except json.JSONDecodeError:
                    logging.warning(f"Malformed jsonl in {fpath}, stopping.")
                    break
            self.fcontents[fpath] += line + "\n"

        return parsed_lines

    def extract_paths(self, fline: LogLine) -> list[str]:
        """Returns a list of all paths in the arguments field"""

        found_paths = []
        for parg in PATH_ARGS:
            if parg in fline.arguments:
                found_paths.append(fline.arguments[parg])

        return found_paths

    def validate_path(self, fline: LogLine) -> float:
        """Binary check for path traversal attempts"""

        paths = self.extract_paths(fline)
        for p in paths:
            path = (self.allowed_path / Path(p)).resolve()
            
            if not path.is_relative_to(self.allowed_path):
                return 1.0

        return 0.0

    def on_modified(self, event):
        """Main handler code"""
        print("UPDATE DETECTED!")

        if type(event) is not FileModifiedEvent:
            return

        flines = self.read_file(event.src_path)
        for fline in flines:
            confidences = Confidences(
                path_traversal=self.validate_path(fline)
            )
            agent_view = AgentView.from_log_line(fline)

            print(f"Recieved a new log from {fline.session_id} (seq {fline.seq})\n")
            dispatch_finding(fline, agent_view, confidences)
