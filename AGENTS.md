# YafYaf TUI

Terminal client for the YafYaf notes API (the Rails app in `../yafyaf`, REST under `/api/`
with Bearer token auth). The themes, the header and its messages, Help, the dialogs and the
startup come from [ouikit](../ouikit), the folder next to this one, shared with ouie, ouifi and
flotte.

## Rules

- Do not git commit unless asked
- The help screen (`?`, or clicking the logo, ouikit's `HelpScreen`) lists every binding that
  has a description and a `group` (`ouikit.shortcuts.ACTIONS` or `GENERAL`) in
  `YafyafApp.HELP_BINDINGS` and `YafyafApp.BINDINGS`; document a new key there
- Code that every app would use goes in ouikit, not here; see its AGENTS.md

## Run

```bash
yaf
```

It refuses to open the TUI unless stdin and stdout are a terminal (ouikit's `start`); `yaf new`
does not go through that check.

## Test

Run both from the git root.

```bash
uv run python -m unittest discover -s tests
uv run ruff check .
```

There is no pytest. `uv sync` installs ouikit from `../ouikit` (`[tool.uv.sources]`), so a
change there shows up here without reinstalling. `ruff` is pinned in the `dev` dependency group, so use
`uv run ruff`, not whatever `ruff` is on PATH. The app tests never reach a server: `support.no_server()`
fails every request a test did not patch, as if nothing were running. Use it in any new test
class that starts the app; without it a local Rails on port 3000 answers those requests and
blanks the saying and score the test set up.

## Structure

```
yafyaf-tui/             # git root + pyproject.toml (run uv commands here)
  yafyaf_tui/           # Python package
    app.py              # Main Textual app (an ouikit BaseApp): state, layout, message handlers
    account_flow.py     # AccountFlow mixin: sign in, token checks, switching servers, sign out
    edit_flow.py        # EditFlow mixin: fetch, edit in the editor, save, delete, the not-saved dialog
    commands.py         # Shell commands that skip the TUI (yaf new)
    config.py           # Server URL resolution, optional config.yaml (theme through ouikit.config, servers)
    accounts.py         # Account (server + email) and TokenStore, the single tokens.yaml
    editor.py           # Draft: a yaf as a temp .md file (date in front matter), edited in $VISUAL or $EDITOR
    api/client.py       # Blocking urllib client for /api/; call it via asyncio.to_thread
    widgets/            # Textual widgets (app_header.py: YafHeader, ouikit's header with the server, score and account;
                        # main_area.py: shows one of the three panes below, plus the footer with the saying and a Refresh button;
                        # yafs_view.py: search box + list, paged from the API; yafs_table.py: its rows;
                        # saying.py: saying + score from the x-yaf-* response headers, polled when idle;
                        # offline_notice.py: replaces the list, and its keys, while the server is down;
                        # yaf_detail.py: one yaf as markdown in place of the list, Enter opens it, e edits)
    screens/            # Textual screens (settings, on ouikit's PanelScreen; login; the not-saved dialog, on ouikit's Dialog)
    styles/             # one .tcss per component, joined after ouikit's in app.STYLE_FILES order
```

## Themes

Themes live in ouikit: the base16 schemes, the terminal's own palette, the picker and the rules
for all of them are in its AGENTS.md. `YafyafApp` is a `ouikit.base_app.BaseApp`, so `t` opens
the picker and the choice is saved to `~/.config/yafyaf-tui/config.yaml`. The theme is not a
setting: Settings only holds the account. `refresh_css` only re-applies TCSS, so
`YafyafApp.apply_theme` also repaints the yaf list, which bakes colors into Rich text, through
`MainArea.set_colors` with colors from `BaseApp.palette`.

Never hardcode a color in a `.tcss` file.

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
mapped onto the palette in `yaf_detail.tcss` under `#yaf-detail-markdown`.

## Tags

A tag is a `#word` in a yaf's content; the server reads them out on save (`Yaf.tags`, `GET
/api/tags` with counts) and a search with `#tag` tokens filters on them. The TUI only displays
what the API gives it: `yafs_table.find_tags` mirrors the server's rule (a letter after the `#`,
not glued to what precedes it, never inside code) to paint tags in the list rows and the yaf
view in `ListColors.tag`, and a click on one posts `TagSelected`. The Tags dropdown next to the
search box (`#` opens it) lists the account's tags with counts, refreshed on every list load;
picking one types `#name` into the search box, runs the search and returns the dropdown to
unselected, so it never holds state of its own. `YafsView.add_tag` is where every way of picking
a tag ends up.

## Servers, config and accounts

`yaf` starts on the server given by `--url` or `YAFYAF_URL` (flag wins), else on the server of
the last account used, else on `https://yafyaf.com`; see `__main__.main` and `config.resolve_url`.
End users configure nothing.

`~/.config/yafyaf-tui/config.yaml` is optional and holds two keys. `theme` is `terminal` (the
default) or the slug of a scheme in ouikit; the picker writes it back with
`ouikit.config.save_theme`, which replaces the `theme:` line rather than rewriting the file, so a
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
