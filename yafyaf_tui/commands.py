"""Commands that run in the shell without starting the TUI."""

import sys
from datetime import date

from .api import ApiConnectionError, ApiError, AuthenticationError, YafyafClient
from .config import TokenStore
from .editor import Draft, DraftError, EditorError


def new_yaf(url: str, token_store: TokenStore, day: date | None = None) -> int:
    """Write a new yaf in $VISUAL or $EDITOR, dated day unless the front matter says otherwise; returns the exit code."""
    token = token_store.load()
    if not token:
        print(f"Not logged in to {url}. Run yaf to log in first.", file=sys.stderr)
        return 1

    draft = Draft.create("", day or date.today(), "new")
    try:
        draft.edit()
    except EditorError as error:
        draft.discard()
        print(error, file=sys.stderr)
        return 1
    try:
        entry = draft.read()
    except DraftError as error:
        return _not_saved(error, draft)
    if not entry.content:
        draft.discard()
        print("Empty yaf, nothing saved.")
        return 0

    try:
        YafyafClient(url, token).create_yaf(entry.content, entry.date)
    except AuthenticationError:
        token_store.clear()
        return _not_saved("Your saved token was rejected. Run yaf to log in again.", draft)
    except (ApiError, ApiConnectionError) as error:
        return _not_saved(error, draft)
    draft.discard()
    print(f"Saved yaf for {entry.date.isoformat()}.")
    return 0


def _not_saved(error: object, draft: Draft) -> int:
    # Keep the file so a failed save does not throw away what was written
    print(f"{error}\nYour yaf is kept in {draft.path}", file=sys.stderr)
    return 1
