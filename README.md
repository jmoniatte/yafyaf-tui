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
yaf new
yaf --version
```

On first start the TUI asks for your YafYaf email and password, exchanges them for an API
token, and saves the token to `~/.config/yafyaf-tui/tokens/yafyaf.com` (readable by you only).
To log out, open Settings (your email at the top right, or `,`) and press Sign out; the TUI
forgets the token and asks for credentials again.

The list shows your yafs newest first and loads more as you scroll. Press `/` to search
(full-text, any word matches), `Enter` to run the search, `Escape` to go back to the list,
`Enter` to edit a yaf, `n` (or the New Yaf button) to write a new one, `r` to reload, `?` for every
shortcut, `,` (or your email at the top right) for your account, `t` for the theme, and `q` to quit.

A yaf opens as a markdown file in `$VISUAL` or `$EDITOR` (`vi` if neither is set), with its date in front matter:

```markdown
---
date: 2026-09-14
---

The yaf's content
```

Change the date there to move the yaf to another day. The front matter only exists in the
file; the yaf's content on the server never includes it. Save and quit to store your changes;
quit without changes, or exit with an error (`:cq` in vim), to leave the yaf as it was. If the
save fails or the date is not valid, the error names the temp file that still holds your edit.

To delete a yaf, clear its content (the front matter can stay) and save and quit. The TUI asks
for confirmation first; Cancel has focus, so pressing Enter keeps the yaf.

The TUI fetches the yaf again before opening it, so you always edit the latest copy. If it was
deleted in the web app, the list refreshes instead. If it is deleted while the editor is open,
your edit is saved as a new yaf.

`yaf new` skips the list: it opens a file with today's date in front matter and, once you save
and quit, creates the yaf and returns to the shell. Leave the content empty to cancel. Log in
with `yaf` first.

## Configuration

Nothing is required. Press `t` to browse the themes: each one applies as the cursor moves, `enter` keeps it and `esc` restores the one you
started on. The choice is written to
`~/.config/yafyaf-tui/config.yaml`, which you can also edit by hand:

```yaml
theme: one-light
```

The default, `terminal`, reads the colours from the terminal itself (xterm OSC 10, 11 and 4
queries). The other themes are [base16 schemes](https://github.com/tinted-theming/schemes)
named by their upstream slug. When the terminal does not answer, `onedark` (or `one-light` on
a light terminal) is used and `terminal` is not offered in the theme picker.

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
