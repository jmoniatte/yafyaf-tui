from textual.widgets import Link


class WebLink(Link):
    """A consistently styled, non-focusable URL link."""

    can_focus = False

    def __init__(self, url: str, label: str | None = None, **kwargs) -> None:
        super().__init__(label or url, url=url, **kwargs)
