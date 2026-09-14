# YafYaf TUI

Terminal client for the [YafYaf](https://github.com/jmoniatte/yafyaf) notes API.

## Installation

```bash
git clone <repo-url>
cd yafyaf-tui
./install.sh
```

Or directly:

```bash
uv tool install ./yafyaf-tui
```

## Configuration

Create `~/.config/yafyaf-tui/config.yaml`:

```yaml
theme: onedark
url: https://yafyaf.example.com
```

On first start the TUI asks for your YafYaf email and password, exchanges them for an API
token, and saves the token to `~/.config/yafyaf-tui/token` (readable by you only). Delete
that file to log out; the TUI will ask for credentials again.

## Usage

```bash
yaf
yaf --version
```

Press `?` for the keyboard shortcuts and `q` to quit.

## Development

```bash
uv run yaf
uv run python -m unittest discover -s tests
uv run ruff check .
```

Releases are git tags without a `v` prefix (`0.1.0`); the version is derived from them by setuptools-scm.
