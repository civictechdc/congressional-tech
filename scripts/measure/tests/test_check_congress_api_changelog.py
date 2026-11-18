"""Tests for scripts/measure/check_congress_api_changelog.py."""
from __future__ import annotations

import base64
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts/measure"))
import check_congress_api_changelog as watcher  # noqa: E402


class CheckCongressApiChangelogTests(unittest.TestCase):
    def test_repo_pin_validates_offline(self) -> None:
        rc = watcher.main(["--pin", str(watcher.DEFAULT_PIN), "--offline"])
        self.assertEqual(rc, 0)

    def test_live_check_unchanged_and_drift_detection(self) -> None:
        pin = watcher.validate_pin(json.loads(watcher.DEFAULT_PIN.read_text(encoding="utf-8")))

        def same_fetch(path: str) -> dict:
            if path.endswith("ChangeLog.md"):
                return {"sha": pin["changelog"]["blob_sha"]}
            doc_key = path.split("/contents/", 1)[1]
            return {"sha": pin["docs"][doc_key]["blob_sha"]}

        ok = watcher.check_live(pin, fetch=same_fetch)
        self.assertTrue(ok["up_to_date"])
        self.assertEqual(ok["drifted"], [])

        updated_md = (
            "# Completed November 2026\n## Change #1\nCommittee meeting update.\n"
            + pin["changelog"]["latest_heading"]
            + "\n## Old change\n"
        )
        encoded = base64.b64encode(updated_md.encode("utf-8")).decode("ascii")

        def drifted_fetch(path: str) -> dict:
            if path.endswith("ChangeLog.md"):
                return {"sha": "f" * 40, "content": encoded}
            doc_key = path.split("/contents/", 1)[1]
            return {"sha": pin["docs"][doc_key]["blob_sha"]}

        drift = watcher.check_live(pin, fetch=drifted_fetch)
        self.assertFalse(drift["up_to_date"])
        self.assertEqual(len(drift["drifted"]), 1)
        self.assertEqual(drift["drifted"][0]["path"], "ChangeLog.md")
        self.assertEqual(len(drift["drifted"][0]["new_sections"]), 1)
        self.assertIn("Committee meeting update", drift["drifted"][0]["new_sections"][0])

    def test_invalid_pin_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "bad.json"
            bad.write_text('{"repo": "x"}')
            with self.assertRaises(ValueError):
                watcher.main(["--pin", str(bad), "--offline"])


if __name__ == "__main__":
    unittest.main()
