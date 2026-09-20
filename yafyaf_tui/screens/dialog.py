from dataclasses import dataclass

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Static

# Escape does nothing in a dialog whose choice must be deliberate
NO_ESCAPE = object()


@dataclass(frozen=True, slots=True)
class DialogButton:
    """One button: what it says, what the dialog returns when it is pressed, and how it looks."""

    label: str
    result: object
    id: str
    # plain, danger or action; base.tcss styles each
    kind: str = "plain"


class Dialog(ModalScreen):
    """A title, a message, an optional one-line detail and a row of buttons, each returning its result."""

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
    ]

    def __init__(
        self,
        title: str,
        message: str,
        buttons: list[DialogButton],
        *,
        detail: str = "",
        focus: str = "",
        escape: object = NO_ESCAPE,
    ) -> None:
        super().__init__()
        self.dialog_title = title
        self.message = message
        self.detail = detail
        self._buttons = buttons
        # The button that starts focused, so Enter is never a surprise; the first one by default
        self._focus = focus or buttons[0].id
        self._escape = escape

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static(self.dialog_title, id="dialog-title", markup=False)
            yield Static(self.message, id="dialog-message", markup=False)
            if self.detail:
                # One line, cut with an ellipsis, so a long detail cannot stretch the dialog
                yield Static(self.detail, id="dialog-detail", markup=False)
            with Horizontal(id="dialog-buttons"):
                for button in self._buttons:
                    yield Button(button.label, id=button.id, classes=f"-{button.kind}")

    def on_mount(self) -> None:
        self.query_one(f"#{self._focus}", Button).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        self.dismiss(next(button.result for button in self._buttons if button.id == event.button.id))

    def action_cancel(self) -> None:
        if self._escape is not NO_ESCAPE:
            self.dismiss(self._escape)
