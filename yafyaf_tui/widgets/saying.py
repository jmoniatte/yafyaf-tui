import asyncio
import random

from textual import work
from textual.timer import Timer
from textual.widgets import Static

from ..api import ApiConnectionError, ApiError, AuthenticationError, YafyafClient
from .app_header import YafHeader

# How long the widget keeps a saying before asking the server for another, as a random range
POLL_SECONDS = (10.0, 30.0)
# A new saying erases the old one from the right, then types itself from the left
ERASE_SECONDS = 0.005
TYPE_SECONDS = 0.025


class Saying(Static):
    """The server's saying, read off the last API response; the score goes to the header.

    Every response repaints both and arms a poll for a fresh one; a response from
    anywhere else in the app pushes the poll back, so it only runs when nothing else has.
    """

    def __init__(self, client: YafyafClient, **kwargs) -> None:
        super().__init__("", id="saying", **kwargs)
        self._client = client
        self._poll: Timer | None = None
        self._shown = ""
        self._target = ""
        self._typing: Timer | None = None

    def on_mount(self) -> None:
        self._client.on_response = self._response_received

    def _response_received(self) -> None:
        # The client runs on a worker thread, so hop back to the app thread before touching widgets
        self.app.call_from_thread(self.sync)

    def sync(self) -> None:
        """Show what the client last saw and arm the next poll, or disarm it when signed out."""
        self._show_saying(self._client.saying)
        self.screen.query_one(YafHeader).show_score(self._client.score)
        self._schedule_poll(enabled=bool(self._client.token))

    def _show_saying(self, saying: str) -> None:
        self._target = saying
        if self.app.animation_level == "none":
            self._shown = saying
            self.update(saying)
        elif self._typing is None:
            # A step already on its way will pick up the new target
            self._type_step()

    def _type_step(self) -> None:
        """Erase one character while the shown text is not the start of the target, then type one."""
        self._typing = None
        if not self._target.startswith(self._shown):
            self._shown = self._shown[:-1]
            delay = ERASE_SECONDS
        elif len(self._shown) < len(self._target):
            self._shown = self._target[: len(self._shown) + 1]
            delay = TYPE_SECONDS
        else:
            return
        self.update(self._shown)
        self._typing = self.set_timer(delay, self._type_step)

    def _schedule_poll(self, enabled: bool = True) -> None:
        if self._poll is not None:
            self._poll.stop()
        self._poll = None
        if enabled:
            self._poll = self.set_timer(random.uniform(*POLL_SECONDS), self._poll_server)

    @work(exclusive=True)
    async def _poll_server(self) -> None:
        self._poll = None
        try:
            await asyncio.to_thread(self._client.me)
        except AuthenticationError:
            # Stop polling with a token the server no longer takes; the next real request asks to log in
            self._schedule_poll(enabled=False)
        except (ApiError, ApiConnectionError):
            self._schedule_poll()
