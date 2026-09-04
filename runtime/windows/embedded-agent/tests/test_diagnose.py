from __future__ import annotations

import sys
import unittest
from pathlib import Path


RUNTIME_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RUNTIME_DIR))

from embedded_runtime_diagnose import parse_tasklist_csv  # noqa: E402


class DiagnoseTests(unittest.TestCase):
    def test_parses_bounded_tasklist_rows(self) -> None:
        value = parse_tasklist_csv('"adownload.exe","1234","Console","1","10,000 K"\r\n')
        self.assertEqual(value, [{"image_name": "adownload.exe", "pid": 1234}])

    def test_ignores_no_task_message(self) -> None:
        self.assertEqual(parse_tasklist_csv('INFO: No tasks are running which match the specified criteria.\r\n'), [])


if __name__ == "__main__":
    unittest.main()
