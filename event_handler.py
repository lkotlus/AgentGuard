"""
AgentGuard Event Handler

Upon an update to any file within a given corpus directory,
the event handler will get the additions to the file. It then
determines which portion(s) of the additon(s) is/are valid jsonl.
The valid lines are analyzed before being sent to the agent.
"""

import json
import logging
from pathlib import Path
from watchdog.events import FileModifiedEvent, LoggingEventHandler

from models import LogLine, AgentView, Confidences

PATH_ARGS = ["target_path", "path"]

class AGEventHandler(LoggingEventHandler):
    def __init__(self, allowed_path: str):
        self.fcontents = {}
        self.allowed_path = Path(allowed_path).resolve()

        super().__init__()

    def read_file(self, fpath: bytes | str) -> list[LogLine]:
        """Returns a list of all valid lines."""

        with open(fpath, "r") as f:
            contents = f.read()

        if not fpath in self.fcontents:
            self.fcontents[fpath] = ""

        # In case of reset_testbed
        if len(contents) < len(self.fcontents[fpath]):
            self.fcontents[fpath] = ""

        parsed_lines = []
        lines = contents[len(self.fcontents[fpath]):].split('\n')
        for line in lines:
            if not line:
                continue
            try:
                parsed_lines.append(LogLine(**json.loads(line)))
                self.fcontents[fpath] += line + '\n'
            except json.JSONDecodeError:
                logging.warning("Incomplete or malformed jsonl.")
                return parsed_lines
        
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
                return 0.0

        return 1.0

    def on_modified(self, event):
        """Main handler code"""

        if type(event) is not FileModifiedEvent:
            return

        flines = self.read_file(event.src_path)
        for fline in flines:
            confidences = Confidences(
                path_traversal=self.validate_path(fline)
            )

            if (confidences.path_traversal == 0):
                print("New operation was clean.\n")
            else:
                print("New log has path issue:")
                print(fline)
                print("\n\n")
