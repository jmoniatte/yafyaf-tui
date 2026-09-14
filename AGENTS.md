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
    config.py           # Config loading (~/.config/yafyaf-tui/config.yaml)
    shortcuts.py        # Help screen contents, read off the bindings
    widgets/            # Textual widgets
    screens/            # Textual screens
    styles/             # base.tcss (layout) + themes/*.tcss (colors)
```

## Config

`~/.config/yafyaf-tui/config.yaml` - see `config.yaml.example`.

- `theme`: onedark or onelight
- `url`: base URL of the YafYaf instance
- `token`: API token from `POST /api/auth_tokens`

## Versions

The version comes from git tags via setuptools-scm. Tags have no `v` prefix. Release by tagging: `git tag 0.1.0`.
