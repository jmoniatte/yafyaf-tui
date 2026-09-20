import argparse
from collections.abc import Sequence

from . import __version__
from .app import YafyafApp
from .commands import new_yaf
from .accounts import TokenStore
from .config import DEFAULT_URL, URL_ENV_VAR, load_config, resolve_url, url_was_given
from .terminal_theme import query_terminal
from .theme import register_terminal_scheme


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Browse and edit YafYaf notes from the terminal.")
    parser.add_argument("--version", action="version", version=f"YafYaf TUI {__version__}")
    parser.add_argument(
        "--url",
        metavar="URL",
        help=f"YafYaf server to start on (default: ${URL_ENV_VAR}, else the last account used, else {DEFAULT_URL})",
    )
    parser.add_argument(
        "--as",
        dest="account",
        metavar="EMAIL",
        help="use this account's stored token instead of the last one used",
    )
    parser.add_argument(
        "command",
        nargs="?",
        choices=["new"],
        help="new: write a new yaf in $VISUAL or $EDITOR instead of opening the list",
    )
    args = parser.parse_args(argv)
    config = load_config()
    store = TokenStore.default()
    current = store.current()
    url = resolve_url(args.url, default=current.url if current else config.servers[0])
    email = args.account or ""

    if args.command == "new":
        raise SystemExit(new_yaf(url, store, email=email, url_given=url_was_given(args.url)))

    account = store.starting_account(url, email, url_was_given(args.url))

    # Must run before Textual takes the tty; a silent terminal just yields None.
    terminal = query_terminal()
    register_terminal_scheme(terminal.scheme, terminal.light_background)
    app = YafyafApp(url=url, config=config, token_store=store, account=account, login_email="" if account else email)
    app.run()


if __name__ == "__main__":
    main()
