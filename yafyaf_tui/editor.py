"""Edit a yaf in the user's $EDITOR as a markdown file with its date in front matter.

The front matter exists only in the file; the API gets the date and content as separate fields.
"""

import os
import re
import shlex
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import yaml

DEFAULT_EDITOR = "vi"
FRONT_MATTER = re.compile(r"\A---[ \t]*\r?\n(.*?)^---[ \t]*(?:\r?\n|\Z)", re.DOTALL | re.MULTILINE)


class EditorError(Exception):
    """The editor could not be started or did not exit cleanly."""


class DraftError(Exception):
    """The saved file cannot be turned back into a yaf."""


@dataclass(frozen=True, slots=True)
class Entry:
    """What the file edits: the yaf's content and date."""

    content: str
    date: date


def editor_command() -> list[str]:
    # $EDITOR may carry arguments, e.g. "code --wait"
    return shlex.split(os.environ.get("EDITOR") or DEFAULT_EDITOR)


def _normalized(text: str) -> str:
    # Blank lines around the body (vim's final newline, the gap after the front matter) are not edits
    return text.strip("\r\n")


def render(entry: Entry) -> str:
    # Match the content's line endings so vim does not show a mixed file full of ^M
    eol = "\r\n" if "\r\n" in entry.content else "\n"
    return f"---{eol}date: {entry.date.isoformat()}{eol}---{eol}{eol}{entry.content}"


def parse(text: str, default_date: date) -> Entry:
    """Split the file into content and date; without front matter the date stays default_date."""
    match = FRONT_MATTER.match(text)
    if not match:
        return Entry(_normalized(text), default_date)
    try:
        fields = yaml.safe_load(match.group(1)) or {}
    except (yaml.YAMLError, ValueError) as error:
        raise DraftError(f"Front matter is not valid: {error}") from None
    if not isinstance(fields, dict):
        raise DraftError("Front matter must be fields like 'date: 2026-09-14'")
    unknown = sorted(str(key) for key in fields if key != "date")
    if unknown:
        raise DraftError(f"Unknown front matter field: {', '.join(unknown)}")
    return Entry(_normalized(text[match.end() :]), _parse_date(fields.get("date", default_date)))


def _parse_date(value: object) -> date:
    # YAML already turns 2026-09-14 into a date; anything else arrives as a string or number
    if type(value) is date:
        return value
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        raise DraftError(f"Front matter date '{value}' is not a date like 2026-09-14") from None


class Draft:
    """A temp .md file holding one yaf while the editor has it."""

    def __init__(self, original: Entry, path: Path) -> None:
        self.original = Entry(_normalized(original.content), original.date)
        self.path = path

    @classmethod
    def create(cls, content: str, day: date, label: str) -> "Draft":
        """Write the file as yaf-<label>-<random>.md; the random part keeps an earlier kept draft safe."""
        entry = Entry(content, day)
        safe_label = re.sub(r"[^A-Za-z0-9_-]", "", label)
        fd, name = tempfile.mkstemp(prefix=f"yaf-{safe_label}-", suffix=".md")
        # newline="" keeps \r\n content byte-identical, so an untouched file reads back unchanged
        with open(fd, "w", encoding="utf-8", newline="") as file:
            file.write(render(entry))
        return cls(entry, Path(name))

    def edit(self) -> None:
        """Run the editor on the file and wait for it; the terminal must be free."""
        command = [*editor_command(), str(self.path)]
        try:
            result = subprocess.run(command)
        except OSError as error:
            raise EditorError(f"Cannot start {command[0]}: {error.strerror or error}") from None
        if result.returncode != 0:
            raise EditorError(f"{command[0]} exited with status {result.returncode}, nothing was saved")

    def read(self) -> Entry:
        with open(self.path, encoding="utf-8", newline="") as file:
            return parse(file.read(), self.original.date)

    def discard(self) -> None:
        self.path.unlink(missing_ok=True)
