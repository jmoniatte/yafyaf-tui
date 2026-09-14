import argparse
from collections.abc import Sequence

from . import __version__
from .app import YafyafApp


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Browse and edit YafYaf notes from the terminal.")
    parser.add_argument("--version", action="version", version=f"YafYaf TUI {__version__}")
    parser.parse_args(argv)

    app = YafyafApp()
    app.run()


if __name__ == "__main__":
    main()
