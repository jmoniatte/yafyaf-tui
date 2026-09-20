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
    app.py              # Main Textual app: state, layout, theme, notifications, message handlers
    account_flow.py     # AccountFlow mixin: sign in, token checks, switching servers, sign out
    edit_flow.py        # EditFlow mixin: fetch, edit in the editor, save, delete, the not-saved dialog
    commands.py         # Shell commands that skip the TUI (yaf new)
    config.py           # Server URL resolution, optional config.yaml (theme, servers)
    accounts.py         # Account (server + email) and TokenStore, the single tokens.yaml
    editor.py           # Draft: a yaf as a temp .md file (date in front matter), edited in $VISUAL or $EDITOR
    api/client.py       # Blocking urllib client for /api/; call it via asyncio.to_thread
    shortcuts.py        # Help screen contents, read off the bindings
    theme.py            # base16 scheme loading, palette derivation
    terminal_theme.py   # OSC queries that read the terminal's own palette before Textual starts
    widgets/            # Textual widgets (main_area.py: shows one of the three panes below, plus the saying;
                        # yafs_view.py: search box + list, paged from the API;
                        # echo.py: saying + score from the x-yaf-* response headers, polled when idle;
                        # offline_notice.py: replaces the list, and its keys, while the server is down;
                        # yaf_detail.py: one yaf as markdown in place of the list, Enter opens it, e edits)
    screens/            # Textual screens (settings, login, theme picker; dialog.py is the base of the
                        # confirm and not-saved dialogs, each a list of DialogButton)
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

Settings (`?` or clicking the email in the header) has a theme dropdown; the picker (`t`) previews as the cursor
moves. Both route through `YafyafApp.set_theme`, which persists the choice;
`apply_theme` alone does not. The palette is served from `YafyafApp.get_css_variables`
rather than baked into `CSS`. `refresh_css` only re-applies TCSS, so the yaf
list, which bakes colors into Rich text, is repainted through
`YafsView.set_colors`.

Never hardcode a color in `base.tcss`.

## Viewing and editing

Enter on a row shows the yaf rendered with Textual's Markdown widget, in place of the list
(`YafDetail`; `MainArea.show_yaf`, `show_list` and `show_offline` decide which pane is up and
whether the saying shows). `e` or Shift+Enter opens the editor from the
list or from the view, and the editor returns where it started: the view shows the saved
content, or the new yaf when the old one was deleted elsewhere. A blanked yaf that is
confirmed deleted drops back to the list. Escape and `q` leave the view; `q` only quits from the list. `y` copies the yaf to the clipboard through OSC 52, or in the view the text selected with the mouse. Both paths fetch the server's copy first through
`YafyafApp._fetch_current`. A save that fails, whether the draft's front matter is bad or the
server refused it, opens `NotSavedDialog` over the kept draft: Edit again reopens that same
draft, Retry (server errors only) sends it again, Discard deletes it. There is no Escape. Shift+Enter only reaches the app in terminals that speak the
kitty keyboard protocol; `e` is the key that works everywhere. The markdown styles are
mapped onto the palette in `base.tcss` under `#yaf-detail-markdown`.

## Servers, config and accounts

`yaf` starts on the server given by `--url` or `YAFYAF_URL` (flag wins), else on the server of
the last account used, else on `https://yafyaf.com`; see `__main__.main` and `config.resolve_url`.
End users configure nothing.

`~/.config/yafyaf-tui/config.yaml` is optional and holds two keys. `theme` is `terminal` (the
default) or the slug of a scheme in `yafyaf_tui/styles/themes/`; the picker writes it back with
`config.save_theme`, which replaces the `theme:` line rather than rewriting the file, so a
hand-written config keeps its comments. `servers` is a list of URLs the login screen offers, for
example production and a local Rails; with one server (the default) the login screen shows no
choice. A server started with `--url` is offered too, even when not listed.

The API tokens are not in the config file. `TokenStore` keeps them all in one mode-600 file,
`~/.config/yafyaf-tui/tokens.yaml`: one entry per `Account` (a server URL and an email), plus
which one is current. On first use `TokenStore.default` imports the per-server directories that
versions before 0.5 kept under `tokens/` and removes them; a token stored there without an email
cannot be filed and has to be logged in again. The login screen writes tokens, a 401 clears the
one it was for, and clearing the current account makes another one current, on the same server
when there is one.

Several accounts, on several servers, can be signed in at once, one shown at a time. The Account
row in Settings is a dropdown of every stored account (`Account.label`: the email alone on
production, `email (host)` elsewhere) plus "Add account...": picking one calls
`YafyafApp.switch_account`, which repoints the client at that account's server, reloads the list
and updates the header, where the server name shows next to the email when it is not production.
`s` cycles through them. Adding one opens the login screen with a Cancel button instead of Quit
and, with several servers configured, a Server dropdown defaulting to the server in use. `yaf --as
EMAIL` (and `yaf new --as EMAIL`) starts on that account, looking on other servers too when no
`--url` was given, or opens the login screen with the email filled in when it has no token.
Signing out is in the same row; the screen closes itself before calling
`YafyafApp.confirm_sign_out` so the confirmation and the login screen behind it are not stacked on
a modal that is on its way out, and sign out falls back to another stored account when there is
one.

## API client

`YafyafClient` uses only the standard library (urllib). It raises `AuthenticationError`
on 401, `ApiError` for other error statuses (message taken from the `error` or `errors`
body), and `ApiConnectionError` when the server cannot be reached. It blocks, so screens
run it through `asyncio.to_thread` inside a `@work` method.

## Versions

The version comes from git tags via setuptools-scm. Tags have no `v` prefix. Release by tagging: `git tag 0.1.0`.
