import argparse
from collections.abc import Sequence

from . import __version__
from .app import YafyafApp
from .config import DEFAULT_URL, URL_ENV_VAR, resolve_url


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Browse and edit YafYaf notes from the terminal.")
    parser.add_argument("--version", action="version", version=f"YafYaf TUI {__version__}")
    parser.add_argument(
        "--url",
        metavar="URL",
        help=f"YafYaf server to talk to (default: ${URL_ENV_VAR} or {DEFAULT_URL})",
    )
    args = parser.parse_args(argv)

    app = YafyafApp(url=resolve_url(args.url))
    app.run()


if __name__ == "__main__":
    main()
