from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, Static

from .confirm_dialog import ConfirmDialog

EDIT_AGAIN = "edit"
RETRY = "retry"
DISCARD = "discard"


class NotSavedDialog(ConfirmDialog):
    """After a failed save: the error and what to do about the edit.

    Returns EDIT_AGAIN (the default, on Enter), RETRY (only offered when the server, not the
    text, was the problem) or DISCARD. There is no Escape: the edit is only in the draft, so
    the user has to choose what becomes of it.
    """

    INITIAL_FOCUS = "#edit-btn"

    def __init__(self, error: str, retry: bool) -> None:
        super().__init__(error, title="Error saving the Yaf")
        self._retry = retry

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static(self.dialog_title, id="dialog-title", markup=False)
            yield Static(self.message, id="dialog-message", markup=False)
            with Horizontal(id="dialog-buttons"):
                yield Button("Discard", id="confirm-btn")
                if self._retry:
                    yield Button("Retry", id="retry-btn")
                yield Button("Edit again", id="edit-btn")

    def result_for(self, button_id: str | None) -> str:
        return {"edit-btn": EDIT_AGAIN, "retry-btn": RETRY}.get(button_id or "", DISCARD)

    def action_cancel(self) -> None:
        pass  # Escape is inherited with the base bindings; discarding must be a deliberate click
