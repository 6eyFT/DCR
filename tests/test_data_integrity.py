import json
import os
import unittest
from pathlib import Path

from load_data import PROJECT_ROOT, load_data, resolve_project_path


class ProjectPathTests(unittest.TestCase):
    def test_load_data_uses_project_root(self):
        original_cwd = Path.cwd()
        try:
            os.chdir("/")
            songs = load_data("data/songs.json")
        finally:
            os.chdir(original_cwd)

        self.assertGreater(len(songs), 0)
        self.assertEqual(resolve_project_path("data/songs.json"), PROJECT_ROOT / "data/songs.json")


class CatalogIntegrityTests(unittest.TestCase):
    def test_asset_references_exist(self):
        for name in ["songs", "intros", "outros", "ads", "ad_intros"]:
            data = json.loads((PROJECT_ROOT / "data" / f"{name}.json").read_text(encoding="utf-8"))
            for item in data:
                for value in item.values():
                    if isinstance(value, str) and value.startswith("assets/"):
                        self.assertTrue(
                            (PROJECT_ROOT / value).exists(),
                            msg=f"Missing asset referenced from {name}.json: {value}",
                        )

    def test_intro_and_outro_song_references_exist(self):
        songs = {
            item["track"]
            for item in json.loads((PROJECT_ROOT / "data" / "songs.json").read_text(encoding="utf-8"))
        }
        for name in ["intros", "outros"]:
            data = json.loads((PROJECT_ROOT / "data" / f"{name}.json").read_text(encoding="utf-8"))
            for item in data:
                if "song" in item:
                    self.assertIn(
                        item["song"],
                        songs,
                        msg=f"{name}.json references a song missing from songs.json: {item['song']}",
                    )


if __name__ == "__main__":
    unittest.main()
