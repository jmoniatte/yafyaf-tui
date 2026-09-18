# YafYaf TUI

Terminal client for the YafYaf notes API (the Rails app in `../yafyaf`, REST under `/api/`
with Bearer token auth).

## Rules

- Do not git commit unless asked
- The settings screen lists every binding that has a description and a `group`
  (`shortcuts.ACTIONS` or `shortcuts.GENERAL`); document a new key there, not in
  `settings_screen.py`

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
    commands.py         # Shell commands that skip the TUI (yaf new)
    config.py           # Server URL resolution, optional config.yaml, TokenStore
    editor.py           # Draft: a yaf as a temp .md file (date in front matter), edited in $VISUAL or $EDITOR
    api/client.py       # Blocking urllib client for /api/; call it via asyncio.to_thread
    shortcuts.py        # Help screen contents, read off the bindings
    theme.py            # base16 scheme loading, palette derivation
    terminal_theme.py   # OSC queries that read the terminal's own palette before Textual starts
    widgets/            # Textual widgets (yafs_view.py: search box + list, paged from the API;
                        # echo.py: saying + score from the x-yaf-* response headers, polled when idle)
    screens/            # Textual screens (settings, login, theme picker)
    styles/             # base.tcss (layout) + themes/*.yaml (base16 schemes)
```

## Themes

`yafyaf_tui/styles/themes/` holds the whole
[base16 catalogue](https://github.com/tinted-theming/schemes), one scheme file
per theme, copied in unmodified - never hand-edit one. `theme.py` maps 11 of
the 16 slots straight onto the TCSS variables `base.tcss` uses and derives the
other two (`$bg-dark`, `$gutter`) from the scheme's greyscale ramp, so adding a
theme means adding a file and nothing else. `config.py` rejects a `theme` that
does not name one of them.

`theme: terminal` (the default) is not a file. `terminal_theme.py` asks the
terminal for its colours with OSC 10, 11 and 4 before Textual starts, maps the
ANSI palette onto base16 slots and derives the rest, and `__main__` registers
the result with `theme.register_terminal_scheme`. A terminal that stays silent,
or whose `$fg` on `$bg` fails `MIN_TEXT_CONTRAST`, registers no scheme: the app
then shows `theme.default_theme()` and the pickers do not list `terminal`. That
default is `one-light` when the terminal reported a light background and
`onedark` otherwise, so a rejected light terminal never gets a dark app. The
surfaces ANSI has no slot for (`base01`, `base02`) are placed by contrast
against the background rather than by a fixed RGB step, which lands the same
distance out on light and dark ramps.
`theme.effective_theme` is the name to compare against or show as current.

Filenames are the upstream scheme slugs verbatim, and that is exactly what
`config.yaml` sets -- no aliases, no renaming. Upstream is inconsistent about
hyphens (`onedark` but `one-light`); follow it rather than tidying it.

`scripts/sync_themes.py` refreshes the directory from upstream. It is the only
place the editorial rule lives: a scheme whose own `$fg` on `$bg` falls below
`MIN_TEXT_CONTRAST` (WCAG AA) is skipped, since `base.tcss` cannot rescue it.
Do not hand-add a scheme the script would reject.

Settings (`?` or the header button) has a theme dropdown; the picker (`t`) previews as the cursor
moves. Both route through `YafyafApp.set_theme`, which persists the choice;
`apply_theme` alone does not. The palette is served from `YafyafApp.get_css_variables`
rather than baked into `CSS`. `refresh_css` only re-applies TCSS, so the yaf
list, which bakes colors into Rich text, is repainted through
`YafsView.set_colors`.

Never hardcode a color in `base.tcss`.

## Server and config

`yaf` talks to `https://yafyaf.com` unless started with `--url` or `YAFYAF_URL` (flag wins);
see `config.resolve_url`. End users configure nothing.

`~/.config/yafyaf-tui/config.yaml` is optional and only holds `theme`: `terminal` (the default)
or the slug of a scheme in `yafyaf_tui/styles/themes/`. The picker writes it back with
`config.save_theme`, which replaces the `theme:` line rather than rewriting the file, so a
hand-written config keeps its comments.

The API tokens are not in the config file. `TokenStore.for_url` keeps them per server in
`~/.config/yafyaf-tui/tokens/<host>[_<port>]/`, one mode-600 file per account email plus a
`current` file naming the one in use. Older installs have a single file at that path with
one token and no email; it is used as-is until the first successful `me` call files it under
its email. The login screen writes tokens, a 401 clears the one it was for, and clearing the
current account makes the next stored one current.

Several accounts can be signed in at once, one shown at a time. The Account row in Settings
is a dropdown of the stored emails plus "Add account...": picking one calls
`YafyafApp.switch_account` (list reloads, score and header follow), adding one opens the login
screen with a Cancel button instead of Quit. `yaf --as EMAIL` (and `yaf new --as EMAIL`) starts
on that account, or opens the login screen with the email filled in when it has no token. The
header shows the email in use. Signing out is in the same row; the screen closes itself before
calling `YafyafApp.confirm_sign_out` so the confirmation and the login screen behind it are not
stacked on a modal that is on its way out, and sign out falls back to another stored account
when there is one.

## API client

`YafyafClient` uses only the standard library (urllib). It raises `AuthenticationError`
on 401, `ApiError` for other error statuses (message taken from the `error` or `errors`
body), and `ApiConnectionError` when the server cannot be reached. It blocks, so screens
run it through `asyncio.to_thread` inside a `@work` method.

## Versions

The version comes from git tags via setuptools-scm. Tags have no `v` prefix. Release by tagging: `git tag 0.1.0`.
