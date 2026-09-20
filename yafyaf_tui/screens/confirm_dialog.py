from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Static


class ConfirmDialog(ModalScreen[bool]):
    """Reusable confirmation dialog modal. Returns True if confirmed, False if cancelled."""

    # Unlike Flotte, Enter does not confirm: focus starts on Cancel, so a reflexive Enter never deletes
    BINDINGS = [
        ("escape", "cancel", "Cancel"),
    ]

    def __init__(
        self,
        message: str,
        title: str = "Confirm",
        confirm_label: str = "Yes",
        cancel_label: str = "No",
        detail: str = "",
    ) -> None:
        super().__init__()
        self.message = message
        self.dialog_title = title
        self.confirm_label = confirm_label
        self.cancel_label = cancel_label
        self.detail = detail

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static(self.dialog_title, id="dialog-title", markup=False)
            yield Static(self.message, id="dialog-message", markup=False)
            if self.detail:
                # One line, cut with an ellipsis, so a long detail cannot stretch the dialog
                yield Static(self.detail, id="dialog-detail", markup=False)
            with Horizontal(id="dialog-buttons"):
                yield Button(self.cancel_label, id="cancel-btn")
                yield Button(self.confirm_label, id="confirm-btn")

    # Subclasses with other buttons change these two rather than the handlers, which Textual runs for every base class
    INITIAL_FOCUS = "#cancel-btn"

    def result_for(self, button_id: str | None) -> object:
        return button_id == "confirm-btn"

    def on_mount(self) -> None:
        self.query_one(self.INITIAL_FOCUS, Button).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        self.dismiss(self.result_for(event.button.id))

    def action_cancel(self) -> None:
        self.dismiss(self.result_for("cancel-btn"))
