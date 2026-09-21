import asyncio
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

from textual.widgets import Input, Markdown, Select, Static

from yafyaf_tui.accounts import TokenStore
from yafyaf_tui.api import (
    Tag,
    ApiConnectionError,
    ApiError,
    NotFoundError,
    Yaf,
    YafPage,
)
from yafyaf_tui.app import YafyafApp
from yafyaf_tui.config import Config
from yafyaf_tui.theme import load_palette
from yafyaf_tui.screens import ConfirmDialog, NotSavedDialog
from yafyaf_tui.widgets import Saying, YafDetail, YafsTable, YafsView
from yafyaf_tui.widgets.yafs_table import DATE_WIDTH, summary_text

from support import patched_tags, ME_ACCOUNT, ONE_PAGE, YAFS, header_message, patched_editor, patched_get, patched_list, patched_me, python_editor, row_text, settle

class YafsViewTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.store = TokenStore(Path(self.tmp.name) / "tokens.yaml")
        self.store.save(ME_ACCOUNT, "good")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _app(self) -> YafyafApp:
        return YafyafApp("http://localhost:3000", Config(), self.store)

    def test_search_reloads_the_list_and_escape_returns_to_it(self) -> None:
        async def exercise() -> None:
            app = self._app()
            match = YafPage(yafs=YAFS[:1], records_count=1)
            with patched_me(), patched_list(ONE_PAGE, match) as list_yafs:
                async with app.run_test(size=(100, 34)) as pilot:
                    await settle(app, pilot)
                    view = app.query_one(YafsView)
                    search = view.query_one("#search", Input)

                    await pilot.press("slash")
                    self.assertTrue(search.has_focus)
                    await pilot.press("escape")
                    self.assertTrue(view.query_one(YafsTable).has_focus)
                    self.assertEqual(list_yafs.call_count, 1)

                    await pilot.press("slash", *"first", "enter")
                    await settle(app, pilot)
                    self.assertEqual(list_yafs.call_args_list[-1].args, ("first", 1))
                    self.assertTrue(view.query_one(YafsTable).has_focus)
                    self.assertEqual(view.query_one(YafsTable).row_count, 1)
                    self.assertEqual(view.query_one("#yafs-status", Static).content, "1 yaf matching 'first'")

                    # Submitting the same search again does not hit the API
                    await pilot.press("slash", "enter")
                    await settle(app, pilot)
                    self.assertEqual(list_yafs.call_count, 2)

        asyncio.run(exercise())

    def test_reaching_the_last_row_fetches_the_next_page(self) -> None:
        async def exercise() -> None:
            app = self._app()
            first = YafPage(yafs=YAFS, records_count=3, next_page={"page": 2, "sort": "date desc"})
            second = YafPage(yafs=(Yaf(id="y3", content="Third [link](http://x) [b]", date=date(2026, 9, 11)),), records_count=3)
            with patched_me(), patched_list(first, second) as list_yafs:
                async with app.run_test(size=(100, 34)) as pilot:
                    await settle(app, pilot)
                    view = app.query_one(YafsView)
                    self.assertEqual(view.query_one("#yafs-status", Static).content, "2 of 3 yafs")

                    await pilot.press("j")
                    await settle(app, pilot)
                    self.assertEqual(list_yafs.call_args_list[-1].args, ("", 2))
                    self.assertEqual(view.query_one(YafsTable).row_count, 3)
                    # A markdown link shows as its label, pointing at the URL; other brackets are not markup
                    summary = view.query_one(YafsTable).get_row_at(2)[1]
                    self.assertEqual(summary.plain, "Third link [b]")
                    link_span = next(span for span in summary.spans if span.style.link)
                    self.assertEqual(summary.plain[link_span.start : link_span.end], "link")
                    self.assertEqual((link_span.style.link, str(link_span.style.color.name)), ("http://x", "#61afef"))
                    self.assertEqual(view.query_one("#yafs-status", Static).content, "3 yafs")

                    await pilot.press("j")
                    await settle(app, pilot)
                    self.assertEqual(list_yafs.call_count, 2)

        asyncio.run(exercise())

    def _editor(self, change: str) -> tuple[str, Path]:
        """An editor that applies a change to the draft text and records the draft's path."""
        record = Path(self.tmp.name) / "draft-path"
        code = (
            "import pathlib, sys; draft = pathlib.Path(sys.argv[1]); "
            f"pathlib.Path({str(record)!r}).write_text(str(draft)); "
            f"text = draft.read_text(); draft.write_text({change})"
        )
        return python_editor(code), record

    def test_e_edits_the_yaf_and_saves_the_change(self) -> None:
        async def exercise() -> None:
            app = self._app()
            editor, record = self._editor("text.replace('Second', 'Changed').replace('09-12', '09-10') + '\\n'")
            on_server = Yaf(id="y2", content="Second yaf, edited on the web", date=date(2026, 9, 12))
            saved = Yaf(id="y2", content="Changed yaf, edited on the web", date=date(2026, 9, 10))
            update = patch("yafyaf_tui.api.client.YafyafClient.update_yaf", return_value=saved)
            with (
                patched_me(),
                patched_list() as list_yafs,
                patched_get(on_server) as get_yaf,
                patched_editor(editor),
                update as update_yaf,
            ):
                async with app.run_test(size=(100, 34)) as pilot:
                    await settle(app, pilot)
                    await pilot.press("j", "e")
                    await settle(app, pilot)

                    # The editor gets the server's copy, not the one the list loaded earlier
                    get_yaf.assert_called_once_with("y2")
                    update_yaf.assert_called_once_with("y2", "Changed yaf, edited on the web", date(2026, 9, 10))
                    draft = Path(record.read_text())
                    self.assertTrue(draft.name.startswith("yaf-y2-"))
                    self.assertFalse(draft.exists())
                    table = app.query_one(YafsTable)
                    self.assertTrue(table.has_focus)
                    self.assertEqual(table.cursor_row, 1)
                    self.assertEqual(row_text(table, 1), ["2026-09-10", "Changed yaf, edited on the web"])
                    self.assertEqual(app.query_one(YafsView).yafs[1], saved)
                    self.assertEqual(header_message(app), "Yaf updated")
                    list_yafs.assert_called_once()

        asyncio.run(exercise())

    def test_enter_shows_the_yaf_as_markdown_and_the_editor_returns_there(self) -> None:
        async def exercise() -> None:
            app = self._app()
            on_server = Yaf(id="y1", content="# Title\n\nSee [docs](https://d.com)\n\n- one\n- two", date=date(2026, 9, 13))
            saved = Yaf(id="y1", content="# Changed\n\nBody", date=date(2026, 9, 13))
            editor, record = self._editor("text.replace('Title', 'Changed')")
            blanked, _ = self._editor("'---\\ndate: 2026-09-13\\n---\\n'")
            after_delete = YafPage(yafs=YAFS[1:], records_count=1)
            with (
                patched_me(),
                patched_list(ONE_PAGE, after_delete) as list_yafs,
                patched_get(on_server) as get_yaf,
                patch("yafyaf_tui.api.client.YafyafClient.update_yaf", return_value=saved) as update_yaf,
                patch("yafyaf_tui.api.client.YafyafClient.delete_yaf") as delete_yaf,
            ):
                async with app.run_test(size=(100, 34)) as pilot:
                    await settle(app, pilot)
                    view = app.query_one(YafsView)
                    detail = app.query_one(YafDetail)
                    markdown = app.query_one(Markdown)
                    self.assertFalse(detail.display)

                    # Enter shows the server's copy, rendered, with the list's keys gone
                    await pilot.press("enter")
                    await settle(app, pilot)
                    get_yaf.assert_called_once_with("y1")
                    self.assertTrue(detail.display)
                    self.assertFalse(view.display)
                    self.assertEqual(app.query_one("#yaf-detail-date", Static).content, "Sunday, September 13, 2026")
                    # The full date and the id sit above the content, the saying stays hidden
                    self.assertFalse(app.query_one(Saying).display)
                    header = app.query_one("#yaf-detail-header")
                    self.assertLess(header.region.y, app.query_one("#yaf-detail-scroll").region.y)
                    yaf_id = app.query_one("#yaf-detail-id", Static)
                    self.assertEqual(yaf_id.content, "y1")
                    self.assertEqual(yaf_id.region.right, header.content_region.right)
                    self.assertEqual([(level, text) for level, text, _ in markdown.table_of_contents], [(1, "Title")])
                    self.assertEqual(len(markdown.query("MarkdownBulletList")), 1)
                    self.assertIs(app.focused, app.query_one("#yaf-detail-scroll"))
                    # A link is a terminal hyperlink as well as a click for the app, like in the list
                    paragraph = markdown.query_one("MarkdownParagraph")
                    link = next(span for span in paragraph._content.spans if not isinstance(span.style, str))
                    self.assertEqual((paragraph._content.plain[link.start : link.end], link.style.link), ("docs", "https://d.com"))
                    with patch.object(app, "open_url") as open_url:
                        await pilot.click(paragraph, offset=(5, 0))
                        await pilot.pause()
                    open_url.assert_called_once_with("https://d.com")

                    # y copies the whole yaf, or just the text selected with the mouse
                    with patch.object(app, "copy_to_clipboard") as copy:
                        await pilot.press("y")
                        await pilot.pause()
                        copy.assert_called_once_with(on_server.content)
                        self.assertEqual(header_message(app), "Yaf copied")
                        await pilot.mouse_down(paragraph, offset=(0, 0))
                        await pilot.hover(paragraph, offset=(3, 0))
                        await pilot.mouse_up(paragraph, offset=(3, 0))
                        await pilot.pause()
                        copy.reset_mock()
                        await pilot.press("y")
                        await pilot.pause()
                        copy.assert_called_once_with("See ")
                        self.assertEqual(header_message(app), "Selection copied")
                    with patch.object(app, "_edit_yaf") as edit:
                        await pilot.press("n")
                        await pilot.pause()
                        edit.assert_not_called()

                    for back in ("escape", "q"):
                        await pilot.press(back)
                        await pilot.pause()
                        self.assertFalse(detail.display)
                        self.assertTrue(view.display)
                        self.assertTrue(app.query_one(Saying).display)
                        self.assertTrue(app.query_one(YafsTable).has_focus)
                        self.assertFalse(app._exit)
                        await pilot.press("enter")
                        await settle(app, pilot)
                        self.assertTrue(detail.display)

                    # Editing from the view comes back to the view, with the saved content
                    with patched_editor(editor):
                        await pilot.press("e")
                        await settle(app, pilot)
                    update_yaf.assert_called_once()
                    self.assertFalse(Path(record.read_text()).exists())
                    self.assertTrue(detail.display)
                    self.assertEqual([(level, text) for level, text, _ in markdown.table_of_contents], [(1, "Changed")])
                    self.assertEqual(row_text(app.query_one(YafsTable), 0), ["2026-09-13", "Changed"])
                    self.assertEqual(header_message(app), "Yaf updated")

                    # Blanking it from the view deletes it, and there is nothing left to view
                    with patched_editor(blanked):
                        await pilot.press("e")
                        await settle(app, pilot)
                    self.assertIsInstance(app.screen, ConfirmDialog)
                    await pilot.press("escape")
                    await settle(app, pilot)
                    self.assertTrue(detail.display)
                    with patched_editor(blanked):
                        await pilot.press("e")
                        await settle(app, pilot)
                    await pilot.click("#confirm-btn")
                    await settle(app, pilot)
                    delete_yaf.assert_called_once_with("y1")
                    self.assertFalse(detail.display)
                    self.assertTrue(view.display)
                    self.assertEqual(list_yafs.call_count, 2)
                    self.assertTrue(app.query_one(YafsTable).has_focus)

                    # Shift+Enter in the list goes straight to the editor, in terminals that can send it
                    editor, record = self._editor("text + '\\n'")
                    with patched_editor(editor):
                        await pilot.press("shift+enter")
                        await settle(app, pilot)
                    self.assertTrue(Path(record.read_text()).name.startswith("yaf-y2-"))
                    self.assertFalse(detail.display)

        asyncio.run(exercise())

    def test_y_copies_the_highlighted_yaf_from_the_list(self) -> None:
        async def exercise() -> None:
            app = self._app()
            with patched_me(), patched_list():
                async with app.run_test(size=(100, 34)) as pilot:
                    await settle(app, pilot)
                    with patch.object(app, "copy_to_clipboard") as copy:
                        await pilot.press("j", "y")
                        await pilot.pause()
                    copy.assert_called_once_with(YAFS[1].content)
                    self.assertEqual(header_message(app), "Yaf copied")

        asyncio.run(exercise())

    def test_nothing_is_saved_without_a_change_and_a_failed_save_keeps_the_draft(self) -> None:
        async def exercise() -> None:
            app = self._app()
            error = ApiError(422, "content is too long")
            update = patch("yafyaf_tui.api.client.YafyafClient.update_yaf", side_effect=error)
            with patched_me(), patched_list(), patched_get(), update as update_yaf:
                async with app.run_test(size=(100, 34), notifications=True) as pilot:
                    await settle(app, pilot)

                    # Saving an untouched file only adds the final newline, which is not an edit
                    editor, record = self._editor("text + '\\n'")
                    with patched_editor(editor):
                        await pilot.press("e")
                        await settle(app, pilot)
                    update_yaf.assert_not_called()
                    self.assertFalse(Path(record.read_text()).exists())
                    self.assertEqual(header_message(app), "")

                    with patched_editor(python_editor("raise SystemExit(3)")) as resumed:
                        await pilot.press("e")
                        await settle(app, pilot)
                    update_yaf.assert_not_called()
                    self.assertEqual(resumed, [True])
                    self.assertIn("exited with status 3", header_message(app))

                    # A bad draft opens a dialog that has to be answered; Discard throws the edit away
                    editor, record = self._editor("text.replace('2026-09-13', '2026-02-30')")
                    with patched_editor(editor):
                        await pilot.press("e")
                        await settle(app, pilot)
                    update_yaf.assert_not_called()
                    draft = Path(record.read_text())
                    self.assertIsInstance(app.screen, NotSavedDialog)
                    self.assertEqual(app.screen.query_one("#dialog-message", Static).content, "An invalid date was entered")
                    self.assertEqual(app.screen.query_one("#dialog-title", Static).content, "Error saving the Yaf")
                    self.assertFalse(app.screen.query("#retry-btn"))  # Sending the same text again cannot help
                    self.assertIs(app.screen.focused, app.screen.query_one("#edit-btn"))
                    await pilot.press("escape")
                    await settle(app, pilot)
                    self.assertIsInstance(app.screen, NotSavedDialog)
                    self.assertTrue(draft.read_text().startswith("---\ndate: 2026-02-30\n---"))
                    await pilot.click("#confirm-btn")
                    await settle(app, pilot)
                    self.assertNotIsInstance(app.screen, NotSavedDialog)
                    self.assertFalse(draft.exists())

                    # Edit again reopens the same draft; a server error then offers a retry
                    with patched_editor(editor):
                        await pilot.press("e")
                        await settle(app, pilot)
                    draft = Path(record.read_text())
                    fixing, record = self._editor("text.replace('2026-02-30', '2026-09-12').replace('First', 'Fixed')")
                    with patched_editor(fixing):
                        await pilot.click("#edit-btn")
                        await settle(app, pilot)
                    self.assertEqual(Path(record.read_text()), draft)
                    update_yaf.assert_called_once_with("y1", "Fixed yaf\nwith a second line", date(2026, 9, 12))
                    self.assertIsInstance(app.screen, NotSavedDialog)
                    self.assertEqual(app.screen.query_one("#dialog-message", Static).content, "content is too long")
                    self.assertTrue(draft.exists())

                    saved = Yaf(id="y1", content="Fixed yaf\nwith a second line", date=date(2026, 9, 12))
                    update_yaf.side_effect = None
                    update_yaf.return_value = saved
                    await pilot.click("#retry-btn")
                    await settle(app, pilot)
                    self.assertEqual(update_yaf.call_count, 2)
                    self.assertNotIsInstance(app.screen, NotSavedDialog)
                    self.assertFalse(draft.exists())
                    self.assertEqual(header_message(app), "Yaf updated")
                    self.assertEqual(row_text(app.query_one(YafsTable), 0), ["2026-09-12", "Fixed yaf"])

        asyncio.run(exercise())

    def test_new_yaf_key_and_button_write_a_new_yaf_in_the_editor(self) -> None:
        async def exercise() -> None:
            app = self._app()
            written = self._editor("'---\\ndate: 2026-09-10\\n---\\n\\nFresh yaf\\n'")
            # Changing only the date of an empty draft still counts as a cancel
            left_empty = self._editor("'---\\ndate: 2026-09-09\\n---\\n\\n'")
            created = Yaf(id="y9", content="Fresh yaf", date=date(2026, 9, 10))
            create = patch("yafyaf_tui.api.client.YafyafClient.create_yaf", return_value=created)
            with patched_me(), patched_list() as list_yafs, create as create_yaf:
                async with app.run_test(size=(100, 34), notifications=True) as pilot:
                    await settle(app, pilot)

                    editor, record = written
                    with patched_editor(editor):
                        await pilot.press("n")
                        await settle(app, pilot)
                    draft = Path(record.read_text())
                    self.assertTrue(draft.name.startswith("yaf-new-"))
                    self.assertFalse(draft.exists())
                    create_yaf.assert_called_once_with("Fresh yaf", date(2026, 9, 10))
                    self.assertEqual(list_yafs.call_count, 2)
                    self.assertEqual(header_message(app), "Yaf created")

                    editor, record = left_empty
                    record.unlink()
                    with patched_editor(editor):
                        await pilot.click("#btn-new-yaf")
                        await settle(app, pilot)
                    self.assertFalse(Path(record.read_text()).exists())
                    create_yaf.assert_called_once()
                    self.assertEqual(header_message(app), "Yaf created")
                    self.assertTrue(app.query_one(YafsTable).has_focus)

        asyncio.run(exercise())

    def test_a_yaf_deleted_elsewhere_refreshes_the_list_or_is_saved_as_a_new_yaf(self) -> None:
        async def exercise() -> None:
            app = self._app()
            after_delete = YafPage(yafs=YAFS[1:], records_count=1)
            deleted = NotFoundError(404, "Record not found")
            editor, record = self._editor("text.replace('Second', 'Rescued')")
            created = Yaf(id="y9", content="Rescued yaf", date=date(2026, 9, 12))
            with (
                patched_me(),
                patched_list(ONE_PAGE, after_delete, ONE_PAGE) as list_yafs,
                patched_editor(editor),
                patch("yafyaf_tui.api.client.YafyafClient.update_yaf", side_effect=deleted) as update_yaf,
                patch("yafyaf_tui.api.client.YafyafClient.create_yaf", return_value=created) as create_yaf,
            ):
                async with app.run_test(size=(100, 34), notifications=True) as pilot:
                    await settle(app, pilot)

                    # Deleted before opening: no editor, and the list reloads without it
                    with patched_get(error=deleted):
                        await pilot.press("e")
                        await settle(app, pilot)
                    self.assertFalse(record.exists())
                    self.assertEqual(list_yafs.call_count, 2)
                    self.assertEqual(row_text(app.query_one(YafsTable), 0), ["2026-09-12", "Second yaf"])
                    self.assertIn("deleted", header_message(app))

                    # Deleted while the editor was open: the edit becomes a new yaf
                    with patched_get():
                        await pilot.press("e")
                        await settle(app, pilot)
                    update_yaf.assert_called_once_with("y2", "Rescued yaf", date(2026, 9, 12))
                    create_yaf.assert_called_once_with("Rescued yaf", date(2026, 9, 12))
                    self.assertFalse(Path(record.read_text()).exists())
                    self.assertEqual(list_yafs.call_count, 3)
                    self.assertIn("saved your edit as a new yaf", header_message(app))

        asyncio.run(exercise())

    def test_blanking_a_yaf_deletes_it_after_confirmation(self) -> None:
        async def exercise() -> None:
            app = self._app()
            # Whitespace under the front matter is as blank as an empty file
            editor, record = self._editor("'---\\ndate: 2026-09-13\\n---\\n  \\n'")
            after_delete = YafPage(yafs=YAFS[1:], records_count=1)
            with (
                patched_me(),
                patched_list(ONE_PAGE, after_delete, after_delete) as list_yafs,
                patched_get(),
                patched_editor(editor),
                patch("yafyaf_tui.api.client.YafyafClient.update_yaf") as update_yaf,
                patch("yafyaf_tui.api.client.YafyafClient.delete_yaf") as delete_yaf,
            ):
                async with app.run_test(size=(100, 34)) as pilot:
                    await settle(app, pilot)

                    # Enter lands on Cancel, so a reflexive Enter does not delete
                    await pilot.press("e")
                    await settle(app, pilot)
                    self.assertIsInstance(app.screen, ConfirmDialog)
                    self.assertEqual(app.screen.query_one("#dialog-message", Static).content, "Delete the yaf from 2026-09-13?")
                    self.assertEqual(app.screen.query_one("#dialog-detail", Static).content, "First yaf")
                    self.assertFalse(Path(record.read_text()).exists())
                    await pilot.press("enter")
                    await settle(app, pilot)
                    self.assertNotIsInstance(app.screen, ConfirmDialog)
                    delete_yaf.assert_not_called()

                    await pilot.press("e")
                    await settle(app, pilot)
                    await pilot.press("escape")
                    await settle(app, pilot)
                    delete_yaf.assert_not_called()

                    await pilot.press("e")
                    await settle(app, pilot)
                    await pilot.click("#confirm-btn")
                    await settle(app, pilot)
                    delete_yaf.assert_called_once_with("y1")
                    update_yaf.assert_not_called()
                    self.assertEqual(list_yafs.call_count, 2)
                    self.assertEqual(row_text(app.query_one(YafsTable), 0), ["2026-09-12", "Second yaf"])
                    self.assertEqual(header_message(app), "Yaf deleted")

                    # Already deleted elsewhere counts as deleted; other failures are reported
                    for failure, message in (
                        (NotFoundError(404, "Record not found"), "Yaf deleted"),
                        (ApiConnectionError("Cannot reach it"), "Not deleted: Cannot reach it"),
                    ):
                        delete_yaf.side_effect = failure
                        await pilot.press("e")
                        await settle(app, pilot)
                        await pilot.click("#confirm-btn")
                        await settle(app, pilot)
                        self.assertEqual(header_message(app), message)
                    self.assertEqual(list_yafs.call_count, 3)

        asyncio.run(exercise())

    def test_the_highlight_follows_the_mouse_and_a_click_opens_the_row(self) -> None:
        async def exercise() -> None:
            app = self._app()
            linked = Yaf(id="y3", content="[docs](https://d.com)", date=date(2026, 9, 1))
            page = YafPage(yafs=(*YAFS, linked), records_count=3)
            with patched_me(), patched_list(page), patched_get(linked) as get_yaf:
                async with app.run_test(size=(100, 34)) as pilot:
                    await settle(app, pilot)
                    table = app.query_one(YafsTable)
                    await pilot.hover(table, offset=(20, 1))
                    await pilot.pause()
                    self.assertEqual(table.cursor_row, 1)
                    await pilot.hover(table, offset=(2, 0))
                    await pilot.pause()
                    self.assertEqual(table.cursor_row, 0)

                    # Over a link, the row is highlighted too
                    link_x = DATE_WIDTH + 3 * table.cell_padding
                    await pilot.hover(table, offset=(link_x, 2))
                    await pilot.pause()
                    self.assertEqual(table.cursor_row, 2)
                    self.assertTrue(any(span.style.underline for span in table.get_row_at(2)[1].spans))
                    await pilot.hover(table, offset=(2, 0))
                    await pilot.pause()

                    await pilot.click(table, offset=(20, 1))
                    await settle(app, pilot)
                    get_yaf.assert_called_once_with("y2")
                    self.assertTrue(app.query_one(YafDetail).display)

        asyncio.run(exercise())

    def test_tags_filter_the_list_from_the_dropdown_a_row_and_the_view(self) -> None:
        async def exercise() -> None:
            app = self._app()
            tagged = Yaf(id="y3", content="Restart #servers now\n\nWith `#code` too", date=date(2026, 9, 1), tags=("servers",))
            page = YafPage(yafs=(*YAFS, tagged), records_count=3)
            with (
                patched_me(),
                patch("yafyaf_tui.api.client.YafyafClient.list_yafs", return_value=page) as list_yafs,
                patched_tags(Tag("servers", 2), Tag("users", 1)),
                patched_get(tagged),
            ):
                async with app.run_test(size=(100, 34)) as pilot:
                    await settle(app, pilot)
                    view = app.query_one(YafsView)
                    selector = app.query_one("#tag-selector", Select)
                    search = app.query_one("#search", Input)
                    self.assertEqual([label for label, _ in selector._options if label], ["servers (2)", "users (1)"])
                    self.assertIs(selector.value, Select.NULL)

                    # # opens the dropdown; picking a tag types it into the search, runs it, and unselects
                    await pilot.press("#")
                    await pilot.pause()
                    self.assertTrue(selector.expanded)
                    self.assertIn(selector, app.focused.ancestors)  # the open overlay has the focus
                    selector.value = "servers"
                    await settle(app, pilot)
                    self.assertEqual(search.value, "#servers")
                    self.assertEqual(list_yafs.call_args.args, ("#servers", 1))
                    self.assertIs(selector.value, Select.NULL)
                    self.assertTrue(app.query_one(YafsTable).has_focus)
                    calls = list_yafs.call_count

                    # The tag in a row is painted in the tag color and a click on it filters too, without repeating it
                    table = app.query_one(YafsTable)
                    summary = table.get_row_at(2)[1]
                    tag_span = next(span for span in summary.spans if span.style.meta.get("tag") == "servers")
                    self.assertEqual(str(tag_span.style.color.name), load_palette("onedark")["purple"])
                    tag_x = DATE_WIDTH + 3 * table.cell_padding + tag_span.start
                    await pilot.click(table, offset=(tag_x, 2))
                    await settle(app, pilot)
                    self.assertEqual((search.value, list_yafs.call_count), ("#servers", calls + 1))

                    # From the view, a click on a tag goes back to the list filtered on it
                    view.load("")
                    await settle(app, pilot)
                    table.move_cursor(row=2)
                    await pilot.press("enter")
                    await settle(app, pilot)
                    self.assertTrue(app.query_one(YafDetail).display)
                    paragraph = app.query_one("MarkdownParagraph")
                    span = next(s for s in paragraph._content.spans if not isinstance(s.style, str) and "tag(" in s.style.meta.get("@click", ""))
                    self.assertEqual(paragraph._content.plain[span.start : span.end], "#servers")
                    await pilot.click(paragraph, offset=(span.start + 1, 0))
                    await settle(app, pilot)
                    self.assertFalse(app.query_one(YafDetail).display)
                    self.assertTrue(view.display)
                    self.assertEqual((search.value, list_yafs.call_args.args), ("#servers", ("#servers", 1)))

        asyncio.run(exercise())

    def test_links_are_blue_underlined_on_hover_and_open_on_click(self) -> None:
        text = summary_text("See [ESI](https://e.com/a?b=1&c=2) and https://x.tv/p, or (https://ooh.directory).", "#61afef")
        self.assertEqual(text.plain, "See ESI and https://x.tv/p, or (https://ooh.directory).")
        links = [(text.plain[span.start : span.end], span.style.link) for span in text.spans]
        self.assertEqual(
            links,
            [
                ("ESI", "https://e.com/a?b=1&c=2"),
                ("https://x.tv/p", "https://x.tv/p"),
                ("https://ooh.directory", "https://ooh.directory"),
            ],
        )
        self.assertTrue(all(span.style.color.name == "#61afef" and not span.style.underline for span in text.spans))
        hovered = summary_text("[a](https://a.com) [b](https://b.com)", hovered_link="https://b.com")
        self.assertEqual([span.style.underline for span in hovered.spans], [False, True])

        # A markdown heading drops its marks and turns the heading color; links inside stay links
        for summary in ("# Portland Trophy Cup", "### Portland Trophy Cup ##"):
            heading = summary_text(summary, heading_color="#e5c07b")
            self.assertEqual((heading.plain, str(heading.style)), ("Portland Trophy Cup", "#e5c07b"))
        heading = summary_text("## See [docs](https://d.com)", "#61afef", heading_color="#e5c07b")
        self.assertEqual((heading.plain, heading.spans[0].style.link), ("See docs", "https://d.com"))
        for not_heading in ("#hashtag", "C# notes", "#"):
            self.assertEqual(summary_text(not_heading, heading_color="#e5c07b").plain, not_heading)

        # Tags take the tag color and carry their name for a click; inline code and URL fragments are left alone
        tagged = summary_text("Restart #Servers, see `#code` and https://x.com/p#anchor #ride-with-gps", tag_color="#c678dd")
        tags = [(tagged.plain[s.start : s.end], s.style.meta.get("tag")) for s in tagged.spans if s.style.meta.get("tag")]
        self.assertEqual(tags, [("#Servers", "servers"), ("#ride-with-gps", "ride-with-gps")])
        self.assertTrue(all(s.style.color.name == "#c678dd" for s in tagged.spans if s.style.meta.get("tag")))

        async def exercise() -> None:
            app = self._app()
            page = YafPage(yafs=(Yaf(id="y1", content="Read [docs](https://d.com) now", date=date(2026, 9, 13)),), records_count=1)
            with (
                patched_me(),
                patched_list(page),
                patched_get() as get_yaf,
                patch.object(YafyafApp, "open_url") as open_url,
            ):
                async with app.run_test(size=(100, 34)) as pilot:
                    await settle(app, pilot)
                    table = app.query_one(YafsTable)
                    # Summary cells start after the padded date column and their own left padding
                    link_x = DATE_WIDTH + 2 * table.cell_padding + table.cell_padding + len("Read ")

                    def link_underlined() -> bool:
                        return any(span.style.underline for span in table.get_row_at(0)[1].spans)

                    await pilot.hover(table, offset=(link_x, 0))
                    await pilot.pause()
                    self.assertTrue(link_underlined())
                    await pilot.hover(table, offset=(link_x - 3, 0))
                    await pilot.pause()
                    self.assertFalse(link_underlined())

                    await pilot.click(table, offset=(link_x + 1, 0))
                    await settle(app, pilot)
                    open_url.assert_called_once_with("https://d.com")
                    get_yaf.assert_not_called()

                    # Outside the link, a click opens the yaf
                    with patched_editor(python_editor("pass")):
                        await pilot.click(table, offset=(link_x - 3, 0))
                        await settle(app, pilot)
                    get_yaf.assert_called_once_with("y1")

        asyncio.run(exercise())

    def test_api_failure_is_reported_in_the_status_line(self) -> None:
        async def exercise() -> None:
            app = self._app()
            error = ApiConnectionError("Cannot reach http://localhost:3000: refused")
            with patched_me(), patch("yafyaf_tui.api.client.YafyafClient.list_yafs", side_effect=error):
                async with app.run_test(size=(100, 34), notifications=True) as pilot:
                    await settle(app, pilot)
                    self.assertEqual(app.query_one("#yafs-status", Static).content, str(error))
                    self.assertEqual(app.query_one(YafsTable).row_count, 0)

        asyncio.run(exercise())
