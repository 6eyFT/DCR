import os
import unittest
from dataclasses import fields
from pathlib import Path

from catalog_loader import PROJECT_ROOT, Intro, Outro, load_catalogs, resolve_project_path


class ProjectPathTests(unittest.TestCase):
    def test_load_catalogs_uses_project_root(self):
        original_cwd = Path.cwd()
        try:
            os.chdir("/")
            catalogs = load_catalogs()
        finally:
            os.chdir(original_cwd)

        self.assertGreater(len(catalogs.songs), 0)
        self.assertEqual(resolve_project_path("data/songs.json"), PROJECT_ROOT / "data/songs.json")


class CatalogIntegrityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalogs = load_catalogs()

    def test_asset_references_exist(self):
        for records in (
            self.catalogs.songs,
            self.catalogs.intros,
            self.catalogs.outros,
            self.catalogs.ads,
            self.catalogs.ad_intros,
        ):
            for item in records:
                for field in fields(item):
                    value = getattr(item, field.name)
                    if isinstance(value, str) and value.startswith("assets/"):
                        self.assertTrue(
                            (PROJECT_ROOT / value).exists(),
                            msg=f"Missing asset referenced by {type(item).__name__}: {value}",
                        )

    def test_intro_and_outro_song_references_exist(self):
        songs = {item.track: item for item in self.catalogs.songs}
        for records in (self.catalogs.intros, self.catalogs.outros):
            for item in records:
                if isinstance(item, (Intro, Outro)) and item.song is not None:
                    self.assertIn(
                        item.song,
                        songs,
                        msg=f"{type(item).__name__} references an unknown song: {item.song}",
                    )
                    self.assertEqual(item.artist, songs[item.song].artist)


if __name__ == "__main__":
    unittest.main()
