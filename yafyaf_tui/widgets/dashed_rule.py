from textual import events
from textual.widgets import Static


class DashedRule(Static):
    """A dashed line as wide as the widget, like Flotte's table rules."""

    def on_mount(self) -> None:
        self.call_after_refresh(self._update_rule)

    def on_resize(self, event: events.Resize) -> None:
        self._update_rule()

    def _update_rule(self) -> None:
        if self.size.width:
            self.update("-" * self.size.width)
