import json
import os
import tempfile
import unittest
from dataclasses import FrozenInstanceError
from pathlib import Path

from catalog_loader import (
    Ad,
    AdIntro,
    CatalogValidationError,
    Intro,
    Outro,
    PROJECT_ROOT,
    Song,
    load_catalogs,
)


class CatalogFixture:
    def __init__(self, root):
        self.root = Path(root)
        (self.root / "data").mkdir(parents=True)
        for directory in ("songs", "intros", "outros", "ads", "ad_intros"):
            (self.root / "assets" / directory).mkdir(parents=True)

        song_track = "assets/songs/Test Song.WAV"
        self.catalogs = {
            "songs": [
                {
                    "id": 1,
                    "track": song_track,
                    "artist": "Test Artist",
                }
            ],
            "intros": [
                {
                    "artist": "Test Artist",
                    "song": song_track,
                    "intro": "assets/intros/Test Intro.wav",
                }
            ],
            "outros": [
                {
                    "artist": "Test Artist",
                    "song": song_track,
                    "outro": "assets/outros/Test Outro.WaV",
                }
            ],
            "ads": [{"ad": "assets/ads/Test Ad.mP3"}],
            "ad_intros": [{"ad_intro": "assets/ads/Test Ad Intro.wav"}],
        }

        for path in (
            song_track,
            "assets/intros/Test Intro.wav",
            "assets/outros/Test Outro.WaV",
            "assets/ads/Test Ad.mP3",
            "assets/ads/Test Ad Intro.wav",
        ):
            self.add_audio(path)
        self.write_all()

    def add_audio(self, path):
        resolved = self.root / path
        resolved.parent.mkdir(parents=True, exist_ok=True)
        resolved.write_bytes(b"fixture audio")

    def write(self, name):
        (self.root / "data" / f"{name}.json").write_text(
            json.dumps(self.catalogs[name]),
            encoding="utf-8",
        )

    def write_all(self):
        for name in self.catalogs:
            self.write(name)


class CatalogLoaderTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.fixture = CatalogFixture(self.temporary_directory.name)

    def assert_catalog_error(self):
        return self.assertRaises(CatalogValidationError)

    def test_valid_catalogs_return_typed_records(self):
        catalogs = load_catalogs(self.fixture.root)

        self.assertIsInstance(catalogs.songs[0], Song)
        self.assertIsInstance(catalogs.intros[0], Intro)
        self.assertIsInstance(catalogs.outros[0], Outro)
        self.assertIsInstance(catalogs.ads[0], Ad)
        self.assertIsInstance(catalogs.ad_intros[0], AdIntro)

    def test_typed_records_and_catalog_collections_are_immutable(self):
        catalogs = load_catalogs(self.fixture.root)

        with self.assertRaises(FrozenInstanceError):
            catalogs.songs[0].artist = "Changed Artist"
        with self.assertRaises(TypeError):
            catalogs.songs[0] = catalogs.songs[0]

    def test_existing_repository_catalogs_accept_placeholder_audio(self):
        audio_fields = {"track", "intro", "outro", "song", "ad", "ad_intro"}
        for name in self.fixture.catalogs:
            records = json.loads(
                (PROJECT_ROOT / "data" / f"{name}.json").read_text(encoding="utf-8")
            )
            (self.fixture.root / "data" / f"{name}.json").write_text(
                json.dumps(records),
                encoding="utf-8",
            )
            for record in records:
                for field in audio_fields:
                    value = record.get(field)
                    if isinstance(value, str):
                        self.fixture.add_audio(value)

        catalogs = load_catalogs(self.fixture.root)

        self.assertGreater(len(catalogs.songs), 0)

    def test_malformed_json(self):
        (self.fixture.root / "data" / "songs.json").write_text("[{", encoding="utf-8")

        with self.assert_catalog_error() as context:
            load_catalogs(self.fixture.root)

        message = str(context.exception)
        self.assertIn("songs.json", message)
        self.assertIn("record <file>", message)
        self.assertIn("field '<json>'", message)
        self.assertIn("malformed JSON", message)

    def test_missing_catalog_file(self):
        (self.fixture.root / "data" / "ads.json").unlink()

        with self.assert_catalog_error() as context:
            load_catalogs(self.fixture.root)

        message = str(context.exception)
        self.assertIn("ads.json", message)
        self.assertIn("catalog file is missing", message)

    def test_incorrect_top_level_json_type(self):
        self.fixture.catalogs["songs"] = {"not": "a list"}
        self.fixture.write("songs")

        with self.assert_catalog_error() as context:
            load_catalogs(self.fixture.root)

        message = str(context.exception)
        self.assertIn("songs.json: record <root>", message)
        self.assertIn("expected a JSON array, got dict", message)

    def test_missing_required_field(self):
        del self.fixture.catalogs["songs"][0]["artist"]
        self.fixture.write("songs")

        with self.assert_catalog_error() as context:
            load_catalogs(self.fixture.root)

        message = str(context.exception)
        self.assertIn("songs.json: record 1, field 'artist'", message)
        self.assertIn("required field is missing", message)

    def test_incorrect_field_type(self):
        self.fixture.catalogs["ads"][0]["ad"] = 42
        self.fixture.write("ads")

        with self.assert_catalog_error() as context:
            load_catalogs(self.fixture.root)

        message = str(context.exception)
        self.assertIn("ads.json: record 1, field 'ad'", message)
        self.assertIn("expected str, got int", message)

    def test_duplicate_id(self):
        second_track = "assets/songs/Second Song.wav"
        self.fixture.add_audio(second_track)
        self.fixture.catalogs["songs"].append(
            {"id": 1, "track": second_track, "artist": "Second Artist"}
        )
        self.fixture.write("songs")

        with self.assert_catalog_error() as context:
            load_catalogs(self.fixture.root)

        message = str(context.exception)
        self.assertIn("songs.json: record 2, field 'id'", message)
        self.assertIn("duplicate ID 1; first used by record 1", message)

    def test_optional_ids_are_also_checked_for_duplicates(self):
        second_ad = "assets/ads/Second Ad.wav"
        self.fixture.add_audio(second_ad)
        self.fixture.catalogs["ads"] = [
            {"id": 8, "ad": "assets/ads/Test Ad.mP3"},
            {"id": 8, "ad": second_ad},
        ]
        self.fixture.write("ads")

        with self.assert_catalog_error() as context:
            load_catalogs(self.fixture.root)

        self.assertIn(
            "ads.json: record 2, field 'id': duplicate ID 8",
            str(context.exception),
        )

    def test_required_id_rejects_non_integer_values(self):
        for invalid_id in (True, False, "1", 1.0, None):
            with self.subTest(invalid_id=invalid_id):
                self.fixture.catalogs["songs"][0]["id"] = invalid_id
                self.fixture.write("songs")

                with self.assert_catalog_error() as context:
                    load_catalogs(self.fixture.root)

                message = str(context.exception)
                self.assertIn("songs.json: record 1, field 'id'", message)
                self.assertIn("expected int", message)

    def test_present_optional_id_rejects_non_integer_values(self):
        for invalid_id in (True, False, "1", 1.0, None):
            with self.subTest(invalid_id=invalid_id):
                self.fixture.catalogs["ads"][0]["id"] = invalid_id
                self.fixture.write("ads")

                with self.assert_catalog_error() as context:
                    load_catalogs(self.fixture.root)

                message = str(context.exception)
                self.assertIn("ads.json: record 1, field 'id'", message)
                self.assertIn("expected int", message)

    def test_unsupported_extension(self):
        unsupported = "assets/ads/Test Ad.ogg"
        self.fixture.add_audio(unsupported)
        self.fixture.catalogs["ads"][0]["ad"] = unsupported
        self.fixture.write("ads")

        with self.assert_catalog_error() as context:
            load_catalogs(self.fixture.root)

        message = str(context.exception)
        self.assertIn("ads.json: record 1, field 'ad'", message)
        self.assertIn("unsupported audio extension '.ogg'", message)

    def test_missing_referenced_audio_file(self):
        (self.fixture.root / "assets" / "ads" / "Test Ad.mP3").unlink()

        with self.assert_catalog_error() as context:
            load_catalogs(self.fixture.root)

        message = str(context.exception)
        self.assertIn("ads.json: record 1, field 'ad'", message)
        self.assertIn("referenced audio file does not exist", message)

    def test_absolute_audio_path_is_rejected(self):
        self.fixture.catalogs["ads"][0]["ad"] = str(
            self.fixture.root / "assets" / "ads" / "Test Ad.mP3"
        )
        self.fixture.write("ads")

        with self.assert_catalog_error() as context:
            load_catalogs(self.fixture.root)

        message = str(context.exception)
        self.assertIn("ads.json: record 1, field 'ad'", message)
        self.assertIn("must be relative to the repository root", message)
        self.assertNotIn("referenced audio file does not exist", message)

    def test_windows_absolute_audio_path_is_rejected(self):
        self.fixture.catalogs["ads"][0]["ad"] = r"C:\\Audio\\Test Ad.mp3"
        self.fixture.write("ads")

        with self.assert_catalog_error() as context:
            load_catalogs(self.fixture.root)

        self.assertIn(
            "ads.json: record 1, field 'ad': must be relative to the repository root",
            str(context.exception),
        )

    def test_parent_traversal_outside_repository_is_rejected(self):
        self.fixture.catalogs["ads"][0]["ad"] = "../Outside Ad.wav"
        self.fixture.write("ads")

        with self.assert_catalog_error() as context:
            load_catalogs(self.fixture.root)

        message = str(context.exception)
        self.assertIn("ads.json: record 1, field 'ad'", message)
        self.assertIn("resolves outside the repository root", message)
        self.assertNotIn("referenced audio file does not exist", message)

    def test_normalized_relative_path_inside_repository_is_accepted(self):
        self.fixture.catalogs["ads"][0]["ad"] = (
            "assets/ads/../ads/Test Ad.mP3"
        )
        self.fixture.write("ads")

        catalogs = load_catalogs(self.fixture.root)

        self.assertEqual(catalogs.ads[0].ad, "assets/ads/../ads/Test Ad.mP3")

    def test_unknown_song_reference(self):
        unknown_song = "assets/songs/Unknown Song.wav"
        self.fixture.add_audio(unknown_song)
        self.fixture.catalogs["intros"][0]["song"] = unknown_song
        self.fixture.write("intros")

        with self.assert_catalog_error() as context:
            load_catalogs(self.fixture.root)

        message = str(context.exception)
        self.assertIn("intros.json: record 1, field 'song'", message)
        self.assertIn("references unknown song", message)

    def test_artist_mismatch(self):
        self.fixture.catalogs["outros"][0]["artist"] = "Wrong Artist"
        self.fixture.write("outros")

        with self.assert_catalog_error() as context:
            load_catalogs(self.fixture.root)

        message = str(context.exception)
        self.assertIn("outros.json: record 1, field 'artist'", message)
        self.assertIn("does not match song artist 'Test Artist'", message)

    def test_wav_and_mp3_extensions_are_case_insensitive(self):
        catalogs = load_catalogs(self.fixture.root)

        self.assertTrue(catalogs.songs[0].track.endswith(".WAV"))
        self.assertTrue(catalogs.ads[0].ad.endswith(".mP3"))
        self.assertTrue(catalogs.outros[0].outro.endswith(".WaV"))

    def test_explicit_project_root_is_independent_of_working_directory(self):
        original_cwd = Path.cwd()
        try:
            os.chdir("/")
            catalogs = load_catalogs(self.fixture.root)
        finally:
            os.chdir(original_cwd)

        self.assertEqual(catalogs.songs[0].track, "assets/songs/Test Song.WAV")

    def test_multiple_validation_errors_are_aggregated(self):
        del self.fixture.catalogs["songs"][0]["artist"]
        self.fixture.catalogs["ads"][0]["ad"] = 42
        self.fixture.catalogs["ad_intros"][0]["ad_intro"] = "assets/ads/Missing.wav"
        self.fixture.write_all()

        with self.assert_catalog_error() as context:
            load_catalogs(self.fixture.root)

        error = context.exception
        self.assertGreaterEqual(len(error.issues), 3)
        message = str(error)
        self.assertIn("songs.json: record 1, field 'artist'", message)
        self.assertIn("ads.json: record 1, field 'ad'", message)
        self.assertIn("ad_intros.json: record 1, field 'ad_intro'", message)

        with self.assert_catalog_error() as repeated_context:
            load_catalogs(self.fixture.root)
        self.assertEqual(message, str(repeated_context.exception))

    def test_one_invalid_path_reports_one_underlying_problem(self):
        self.fixture.catalogs["ads"][0]["ad"] = "assets/ads/Bad.ogg"
        self.fixture.write("ads")

        with self.assert_catalog_error() as context:
            load_catalogs(self.fixture.root)

        matching_issues = [
            issue
            for issue in context.exception.issues
            if issue.catalog.value == "ads"
            and issue.record == 1
            and issue.field == "ad"
        ]
        self.assertEqual(len(matching_issues), 1)
        self.assertIn("unsupported audio extension", matching_issues[0].reason)

    def test_all_five_catalogs_are_checked_in_one_load(self):
        (self.fixture.root / "data" / "songs.json").write_text("[{", encoding="utf-8")
        (self.fixture.root / "data" / "ads.json").unlink()

        with self.assert_catalog_error() as context:
            load_catalogs(self.fixture.root)

        message = str(context.exception)
        self.assertIn("songs.json", message)
        self.assertIn("ads.json", message)


if __name__ == "__main__":
    unittest.main()
