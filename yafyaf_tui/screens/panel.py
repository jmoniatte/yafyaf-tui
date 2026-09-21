from textual import on
from textual.screen import ModalScreen
from textual.widgets import Button


class PanelScreen(ModalScreen):
    """A panel over the list: Escape or a click outside closes it. Settings and Help are panels."""

    BINDINGS = [
        ("escape", "dismiss", "Close"),
    ]

    @on(Button.Pressed, "#btn-close")
    def _close(self, event: Button.Pressed) -> None:
        event.stop()
        self.dismiss()

    def on_click(self, event) -> None:
        """Dismiss on a click outside the panel, but let a dropdown inside it work."""
        if event.widget is self:
            self.dismiss()
