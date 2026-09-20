"""Commands that run in the shell without starting the TUI."""

import sys
from datetime import date

from .api import ApiConnectionError, ApiError, AuthenticationError, YafyafClient
from .accounts import TokenStore
from .editor import Draft, DraftError, EditorError


def new_yaf(
    url: str, token_store: TokenStore, day: date | None = None, email: str = "", url_given: bool = False
) -> int:
    """Write a new yaf in $VISUAL or $EDITOR, dated day unless the front matter says otherwise; returns the exit code.

    The account is picked the way the TUI picks it, so `yaf new --as EMAIL` lands on the same account as `yaf --as EMAIL`.
    """
    account = token_store.starting_account(url, email, url_given)
    token = token_store.token(account)
    if not token:
        who = f"as {email} " if email else ""
        print(f"Not logged in {who}to {url}. Run yaf to log in first.", file=sys.stderr)
        return 1
    url = account.url

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

    client = YafyafClient(url, token)
    try:
        client.create_yaf(entry.content, entry.date)
    except AuthenticationError:
        token_store.clear(account)
        return _not_saved("Your saved token was rejected. Run yaf to log in again.", draft)
    except (ApiError, ApiConnectionError) as error:
        return _not_saved(error, draft)
    draft.discard()
    print(f"Saved yaf for {entry.date.isoformat()}.")
    if client.saying:
        print(client.saying)
    return 0


def _not_saved(error: object, draft: Draft) -> int:
    # Keep the file so a failed save does not throw away what was written
    print(f"{error}\nYour yaf is kept in {draft.path}", file=sys.stderr)
    return 1
