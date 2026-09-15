import unittest
from datetime import date

from yafyaf_tui.editor import Draft, DraftError, Entry, parse, render

DAY = date(2026, 9, 14)


class FrontMatterTest(unittest.TestCase):
    def test_render_and_parse_round_trip_and_keep_line_endings(self) -> None:
        text = render(Entry("# Title\nbody", DAY))
        self.assertEqual(text, "---\ndate: 2026-09-14\n---\n\n# Title\nbody")
        self.assertEqual(parse(text + "\n", date(2000, 1, 1)), Entry("# Title\nbody", DAY))

        windows = render(Entry("one\r\ntwo", DAY))
        self.assertEqual(windows, "---\r\ndate: 2026-09-14\r\n---\r\n\r\none\r\ntwo")
        self.assertEqual(parse(windows, date(2000, 1, 1)), Entry("one\r\ntwo", DAY))

    def test_parse_uses_the_default_date_when_front_matter_is_missing_or_has_no_date(self) -> None:
        self.assertEqual(parse("\njust text\n", DAY), Entry("just text", DAY))
        self.assertEqual(parse("---\n---\nbody", DAY), Entry("body", DAY))
        # A leading horizontal rule with no closing fence is content, not front matter
        self.assertEqual(parse("---\nbody", DAY), Entry("---\nbody", DAY))
        self.assertEqual(parse("---\ndate: '2026-09-01'\n---\nbody", DAY), Entry("body", date(2026, 9, 1)))

    def test_parse_rejects_bad_front_matter(self) -> None:
        cases = {
            "---\ndate: 2026-02-30\n---\nbody": "Front matter is not valid",
            "---\ndate: yesterday\n---\nbody": "'yesterday' is not a date",
            "---\ndate: 2026-09-14 10:00\n---\nbody": "is not a date",
            "---\ndate: 2026-09-14\ntags: [a]\n---\nbody": "Unknown front matter field: tags",
            "---\n- a list\n---\nbody": "must be fields",
            "---\ndate: [unclosed\n---\nbody": "Front matter is not valid",
        }
        for text, message in cases.items():
            with self.subTest(text=text), self.assertRaises(DraftError) as raised:
                parse(text, DAY)
            self.assertIn(message, str(raised.exception))

    def test_draft_is_named_after_the_yaf_and_reads_back_what_it_wrote(self) -> None:
        draft = Draft.create("body\n", DAY, "../y1")
        try:
            self.assertRegex(draft.path.name, r"^yaf-y1-\w+\.md$")
            self.assertEqual(draft.original, Entry("body", DAY))
            self.assertEqual(draft.read(), draft.original)
        finally:
            draft.discard()
        self.assertFalse(draft.path.exists())
