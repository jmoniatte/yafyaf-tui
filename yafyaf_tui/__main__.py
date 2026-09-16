import argparse
from collections.abc import Sequence

from . import __version__
from .app import YafyafApp
from .commands import new_yaf
from .config import DEFAULT_URL, URL_ENV_VAR, TokenStore, resolve_url
from .terminal_theme import query_terminal
from .theme import register_terminal_scheme


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Browse and edit YafYaf notes from the terminal.")
    parser.add_argument("--version", action="version", version=f"YafYaf TUI {__version__}")
    parser.add_argument(
        "--url",
        metavar="URL",
        help=f"YafYaf server to talk to (default: ${URL_ENV_VAR} or {DEFAULT_URL})",
    )
    parser.add_argument(
        "command",
        nargs="?",
        choices=["new"],
        help="new: write a new yaf in $VISUAL or $EDITOR instead of opening the list",
    )
    args = parser.parse_args(argv)
    url = resolve_url(args.url)

    if args.command == "new":
        raise SystemExit(new_yaf(url, TokenStore.for_url(url)))

    # Must run before Textual takes the tty; a silent terminal just yields None.
    terminal = query_terminal()
    register_terminal_scheme(terminal.scheme, terminal.light_background)
    app = YafyafApp(url=url)
    app.run()


if __name__ == "__main__":
    main()
