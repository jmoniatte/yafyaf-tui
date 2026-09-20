"""Textual's Markdown widget with terminal hyperlinks on its links, like the list's links have."""

import ast

from textual.content import Content, Span
from textual.style import Style
from textual.widgets import Markdown
from textual.widgets.markdown import MarkdownBlock


def _with_hyperlink(style: Style | str) -> Style | str:
    """Textual only gives a markdown link a click action; add the terminal hyperlink the list's links carry."""
    if isinstance(style, str) or style.link is not None:
        return style
    action = style.meta.get("@click", "")
    if not action.startswith("link("):
        return style
    return style + Style(link=ast.literal_eval(action[5:-1]))


class _LinkedBlock:
    def _token_to_content(self, token) -> Content:
        content = super()._token_to_content(token)
        spans = [Span(span.start, span.end, _with_hyperlink(span.style)) for span in content.spans]
        return Content(content.plain, spans)


class YafMarkdown(Markdown):
    """Markdown whose links the terminal can open itself, as it can the list's, not only through the app."""

    _linked: dict[type[MarkdownBlock], type[MarkdownBlock]] = {}

    def get_block_class(self, block_name: str) -> type[MarkdownBlock]:
        block = super().get_block_class(block_name)
        if block not in self._linked:
            self._linked[block] = type(block.__name__, (_LinkedBlock, block), {})
        return self._linked[block]
