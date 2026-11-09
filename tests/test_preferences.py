"""Préférences : stockées dans %APPDATA%\EdenDisk, reprise de l'ancien config.json (2.0.0 et avant)."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
import backend  # noqa: E402


class Preferences(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.appdata = self.root / "AppData"
        self.cwd = self.root / "Program Files" / "EdenDisk"
        self.cwd.mkdir(parents=True)
        self.old_cwd = os.getcwd()
        os.chdir(self.cwd)
        self.env = mock.patch.dict(os.environ, {"APPDATA": str(self.appdata)})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        os.chdir(self.old_cwd)
        self.tmp.cleanup()

    def test_default_is_french(self):
        self.assertEqual(backend.load_preferences(), {"language": "fr"})

    def test_saved_in_appdata_not_in_current_folder(self):
        backend.save_preferences({"language": "en"})
        self.assertTrue((self.appdata / "EdenDisk" / "config.json").exists())
        self.assertFalse((self.cwd / "config.json").exists())
        self.assertEqual(backend.load_preferences()["language"], "en")

    def test_reads_legacy_file_then_appdata_wins(self):
        (self.cwd / "config.json").write_text(json.dumps({"language": "en"}), encoding="utf-8")
        self.assertEqual(backend.load_preferences()["language"], "en")
        backend.save_preferences({"language": "fr"})
        self.assertEqual(backend.load_preferences()["language"], "fr")

    def test_corrupt_file_ignored(self):
        path = self.appdata / "EdenDisk" / "config.json"
        path.parent.mkdir(parents=True)
        path.write_text("{pas du json", encoding="utf-8")
        self.assertEqual(backend.load_preferences(), {"language": "fr"})


if __name__ == "__main__":
    unittest.main()
