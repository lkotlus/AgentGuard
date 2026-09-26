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

from models import LogLine, AgentView

PATH_ARGS = ["target_path", "path"]

class AGEventHandler(LoggingEventHandler):
    def __init__(self, allowed_path: str):
        self.fcontents = {}
        self.allowed_path = Path(allowed_path).resolve()

        super().__init__()

    def read_file(self, fpath: bytes | str) -> list[LogLine]:
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
                parsed_lines[-1].pop("annotations", None)
                self.fcontents[fpath] += line + '\n'
            except json.JSONDecodeError:
                logging.warning("Incomplete or malformed jsonl.")
                return parsed_lines
        
        return parsed_lines

    def extract_paths(self, fline: LogLine) -> list[str]:
        found_paths = []
        for parg in PATH_ARGS:
            if parg in fline.arguments:
                found_paths.append(fline.arguments[parg])

        return found_paths

    def validate_path(self, fline: LogLine) -> bool:
        paths = self.extract_paths(fline)
        
        for p in paths:
            path = (self.allowed_path / Path(p)).resolve()
            
            if not path.is_relative_to(self.allowed_path):
                return False

        return True

    def on_modified(self, event):
        if type(event) is not FileModifiedEvent:
            return

        flines = self.read_file(event.src_path)
        for fline in flines:
            if (self.validate_path(fline)):
                print("New operation was clean.\n")
            else:
                print("New log has path issue:\n")
                print(fline)
                print("\n\n")
