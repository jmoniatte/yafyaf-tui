"""Textual's Markdown widget with terminal hyperlinks on its links, like the list's links have."""

import ast

from textual.color import Color
from textual.content import Content, Span
from textual.style import Style
from textual.widgets import Markdown
from textual.widgets.markdown import MarkdownBlock

from .yafs_table import TagSelected, find_tags


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
        # Inline code is its own span; a tag inside it is text, as on the server
        code = [(s.start, s.end) for s in content.spans if s.style == ".code_inline"]
        tag_color = self._markdown_ref().tag_color
        for start, end, name in find_tags(content.plain):
            if not any(a <= start < b for a, b in code):
                style = Style.from_meta({"@click": f"tag({name!r})"})
                if tag_color:
                    style = style + Style(foreground=Color.parse(tag_color))
                spans.append(Span(start, end, style))
        return Content(content.plain, spans)

    async def action_tag(self, name: str) -> None:
        self.post_message(TagSelected(name))


class YafMarkdown(Markdown):
    """Markdown whose links the terminal can open itself, as it can the list's, and whose tags filter the list."""

    _linked: dict[type[MarkdownBlock], type[MarkdownBlock]] = {}

    def __init__(self, tag_color: str = "", **kwargs) -> None:
        super().__init__(**kwargs)
        self.tag_color = tag_color

    def get_block_class(self, block_name: str) -> type[MarkdownBlock]:
        block = super().get_block_class(block_name)
        if block not in self._linked:
            self._linked[block] = type(block.__name__, (_LinkedBlock, block), {})
        return self._linked[block]
