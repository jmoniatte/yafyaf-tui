# YafYaf TUI

Terminal client for the YafYaf notes API (the Rails app in `../yafyaf`, REST under `/api/`
with Bearer token auth).

## Rules

- Do not git commit unless asked
- The help screen lists every binding that has a description and a `group`
  (`shortcuts.ACTIONS` or `shortcuts.GENERAL`); document a new key there, not in
  `help_screen.py`

## Run

```bash
yaf
```

## Test

Run both from the git root.

```bash
uv run python -m unittest discover -s tests
uv run ruff check .
```

There is no pytest. `ruff` is pinned in the `dev` dependency group, so use
`uv run ruff`, not whatever `ruff` is on PATH.

## Structure

```
yafyaf-tui/             # git root + pyproject.toml (run uv commands here)
  yafyaf_tui/           # Python package
    app.py              # Main Textual app
    config.py           # Server URL resolution, optional config.yaml, TokenStore
    api/client.py       # Blocking urllib client for /api/; call it via asyncio.to_thread
    shortcuts.py        # Help screen contents, read off the bindings
    widgets/            # Textual widgets
    screens/            # Textual screens
    styles/             # base.tcss (layout) + themes/*.tcss (colors)
```

## Server and config

`yaf` talks to `https://yafyaf.com` unless started with `--url` or `YAFYAF_URL` (flag wins);
see `config.resolve_url`. End users configure nothing.

`~/.config/yafyaf-tui/config.yaml` is optional and only holds `theme` (onedark or onelight).

The API token is not in the config file. `TokenStore.for_url` keeps one token per server in
`~/.config/yafyaf-tui/tokens/<host>[_<port>]` (mode 600); the login screen writes it and a
401 clears it.

## API client

`YafyafClient` uses only the standard library (urllib). It raises `AuthenticationError`
on 401, `ApiError` for other error statuses (message taken from the `error` or `errors`
body), and `ApiConnectionError` when the server cannot be reached. It blocks, so screens
run it through `asyncio.to_thread` inside a `@work` method.

## Versions

The version comes from git tags via setuptools-scm. Tags have no `v` prefix. Release by tagging: `git tag 0.1.0`.
