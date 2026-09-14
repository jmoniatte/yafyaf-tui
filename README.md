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

## Usage

```bash
yaf
yaf --version
```

On first start the TUI asks for your YafYaf email and password, exchanges them for an API
token, and saves the token to `~/.config/yafyaf-tui/tokens/yafyaf.com` (readable by you only).
Delete that file to log out; the TUI will ask for credentials again.

Press `?` for the keyboard shortcuts and `q` to quit.

## Configuration

Nothing is required. To change the color theme, create `~/.config/yafyaf-tui/config.yaml`:

```yaml
theme: onelight
```

### Talking to another server

Developers can point the TUI at a local YafYaf with a flag or an environment variable. The
flag wins over the variable, and the header shows the server whenever it is not
`https://yafyaf.com`. Each server gets its own token file under `~/.config/yafyaf-tui/tokens/`.

```bash
yaf --url http://localhost:3000
YAFYAF_URL=http://localhost:3000 yaf
```

## Development

```bash
uv run yaf
uv run python -m unittest discover -s tests
uv run ruff check .
```

Releases are git tags without a `v` prefix (`0.1.0`); the version is derived from them by setuptools-scm.
