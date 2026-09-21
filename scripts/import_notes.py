#!/usr/bin/env python3
"""Import a folder of markdown notes as yafs, one file per yaf.

Each file starts with YAML front matter giving the yaf's `date`; everything after it is the
content. The first content line is what the list shows, so make it a heading that says what
the note is. Files named REPORT.md are skipped.

    uv run python scripts/import_notes.py NOTES_DIR --url http://localhost:8000 --email notes@yafyaf.com
    uv run python scripts/import_notes.py NOTES_DIR --as notes@yafyaf.com --dry-run

With --email the script asks for the password, logs in, and stores the token like the app
does, so `yaf --as EMAIL` can browse the result afterwards. With --as it uses a stored token.
"""

import argparse
import getpass
import re
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from yafyaf_tui.accounts import Account, TokenStore  # noqa: E402
from yafyaf_tui.api import ApiConnectionError, ApiError, YafyafClient  # noqa: E402
from yafyaf_tui.config import DEFAULT_URL, normalize_url  # noqa: E402

FRONT_MATTER = re.compile(r"\A---\s*\n(.*?)^---\s*\n", re.DOTALL | re.MULTILINE)


@dataclass(frozen=True, slots=True)
class Note:
    path: Path
    date: date
    content: str

    @property
    def title(self) -> str:
        return next((line.strip() for line in self.content.splitlines() if line.strip()), "")


def read_note(path: Path) -> Note:
    text = path.read_text(encoding="utf-8")
    match = FRONT_MATTER.match(text)
    if not match:
        raise ValueError(f"{path}: no front matter")
    fields = yaml.safe_load(match.group(1)) or {}
    day = fields.get("date")
    if not isinstance(day, date):
        raise ValueError(f"{path}: front matter needs a date like 2026-09-14")
    content = text[match.end() :].strip("\n")
    if not content.strip():
        raise ValueError(f"{path}: empty note")
    return Note(path, day, content)


def read_notes(folder: Path) -> list[Note]:
    paths = sorted(p for p in folder.rglob("*.md") if p.name != "REPORT.md")
    return [read_note(path) for path in paths]


def import_notes(notes: list[Note], client: YafyafClient) -> int:
    """Create one yaf per note; returns how many were created. Stops at the first failure."""
    for index, note in enumerate(notes, 1):
        try:
            client.create_yaf(note.content, note.date)
        except (ApiError, ApiConnectionError) as error:
            print(f"Stopped at {note.path}: {error}", file=sys.stderr)
            return index - 1
        print(f"{index:4}/{len(notes)}  {note.date}  {note.title}")
    return len(notes)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("folder", type=Path)
    parser.add_argument("--url", default=DEFAULT_URL, help=f"server (default {DEFAULT_URL})")
    who = parser.add_mutually_exclusive_group(required=True)
    who.add_argument("--as", dest="account", metavar="EMAIL", help="use this account's stored token")
    who.add_argument("--email", help="log in as this account, asking for the password, and store its token")
    parser.add_argument("--dry-run", action="store_true", help="list what would be created and stop")
    args = parser.parse_args(argv)

    try:
        notes = read_notes(args.folder)
    except ValueError as error:
        print(error, file=sys.stderr)
        return 1
    if args.dry_run:
        for note in notes:
            print(f"{note.date}  {len(note.content):6}  {note.title}")
        print(f"{len(notes)} notes")
        return 0

    url = normalize_url(args.url)
    store = TokenStore.default()
    client = YafyafClient(url)
    if args.email:
        try:
            session = client.login(args.email, getpass.getpass(f"Password for {args.email} on {url}: "))
        except (ApiError, ApiConnectionError) as error:
            print(f"Login failed: {error}", file=sys.stderr)
            return 1
        store.save(Account(url, session.user.email), session.token)
        print(f"Logged in as {session.user.email}; token stored for yaf --as {session.user.email}")
    else:
        client.token = store.token(Account(url, args.account))
        if not client.token:
            print(f"No stored token for {args.account} on {url}. Run yaf --url {url} --as {args.account} to log in.", file=sys.stderr)
            return 1

    created = import_notes(notes, client)
    print(f"Created {created} of {len(notes)} yafs on {url}")
    return 0 if created == len(notes) else 1


if __name__ == "__main__":
    raise SystemExit(main())
