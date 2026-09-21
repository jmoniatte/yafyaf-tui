import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from import_notes import import_notes, read_notes  # noqa: E402

from yafyaf_tui.api import ApiError, YafyafClient  # noqa: E402


class ImportNotesTest(unittest.TestCase):
    def test_reads_dated_notes_in_order_and_creates_one_yaf_each(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            (folder / "02-b.md").write_text("---\ndate: 2026-09-14\nsource: b.md\n---\n# B: Second\n\nbody\n")
            (folder / "01-a.md").write_text("---\ndate: 2024-01-31\n---\n\n# A: First\n\n```bash\nls\n```\n")
            (folder / "REPORT.md").write_text("not a note")
            notes = read_notes(folder)
            self.assertEqual([(n.date, n.title) for n in notes], [(date(2024, 1, 31), "# A: First"), (date(2026, 9, 14), "# B: Second")])
            self.assertEqual(notes[0].content, "# A: First\n\n```bash\nls\n```")

            client = YafyafClient("http://localhost:3000", token="t")
            with patch.object(YafyafClient, "create_yaf") as create_yaf:
                self.assertEqual(import_notes(notes, client), 2)
            self.assertEqual([c.args for c in create_yaf.call_args_list], [(notes[0].content, date(2024, 1, 31)), (notes[1].content, date(2026, 9, 14))])

            # A failure stops the run and reports how far it got, so a rerun can pick up from there
            with patch.object(YafyafClient, "create_yaf", side_effect=[None, ApiError(422, "too long")]):
                self.assertEqual(import_notes(notes, client), 1)

    def test_rejects_notes_without_a_date(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "x.md").write_text("# no front matter\n")
            with self.assertRaises(ValueError):
                read_notes(Path(tmp))
            (Path(tmp) / "x.md").write_text("---\ndate: soon\n---\n# x\n")
            with self.assertRaises(ValueError):
                read_notes(Path(tmp))


if __name__ == "__main__":
    unittest.main()
