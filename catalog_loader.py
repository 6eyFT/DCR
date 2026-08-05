"""Typed loading and validation for all Diamond City Radio catalogs."""

import json
from dataclasses import dataclass
from enum import Enum
from pathlib import Path, PureWindowsPath


PROJECT_ROOT = Path(__file__).resolve().parent
SUPPORTED_AUDIO_EXTENSIONS = frozenset({".mp3", ".wav"})


class CatalogName(str, Enum):
    SONGS = "songs"
    INTROS = "intros"
    OUTROS = "outros"
    ADS = "ads"
    AD_INTROS = "ad_intros"

    @property
    def filename(self):
        return f"{self.value}.json"


@dataclass(frozen=True)
class Song:
    id: int
    track: str
    artist: str


@dataclass(frozen=True)
class Intro:
    artist: str
    intro: str
    song: str | None = None
    id: int | None = None


@dataclass(frozen=True)
class Outro:
    artist: str
    outro: str
    song: str | None = None
    id: int | None = None


@dataclass(frozen=True)
class Ad:
    ad: str
    id: int | None = None


@dataclass(frozen=True)
class AdIntro:
    ad_intro: str
    id: int | None = None


@dataclass(frozen=True)
class Catalogs:
    songs: tuple[Song, ...]
    intros: tuple[Intro, ...]
    outros: tuple[Outro, ...]
    ads: tuple[Ad, ...]
    ad_intros: tuple[AdIntro, ...]


@dataclass(frozen=True)
class ValidationIssue:
    catalog: CatalogName
    record: int | str
    field: str
    reason: str

    def __str__(self):
        return (
            f"{self.catalog.filename}: record {self.record}, "
            f"field '{self.field}': {self.reason}"
        )


class CatalogValidationError(ValueError):
    def __init__(self, issues):
        self.issues = tuple(issues)
        count = len(self.issues)
        label = "problem" if count == 1 else "problems"
        details = "\n".join(f"- {issue}" for issue in self.issues)
        super().__init__(f"Catalog validation failed with {count} {label}:\n{details}")


def resolve_project_path(path, project_root=None):
    candidate = Path(path)
    if candidate.is_absolute():
        return candidate
    root = PROJECT_ROOT if project_root is None else Path(project_root)
    return root / candidate


def asset_exists(path, project_root=None):
    return resolve_project_path(path, project_root=project_root).is_file()


def _add_issue(issues, catalog, record, field, reason):
    issues.append(
        ValidationIssue(
            catalog=catalog,
            record=record,
            field=field,
            reason=reason,
        )
    )


def _load_json(catalog, project_root, issues):
    path = project_root / "data" / catalog.filename
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        _add_issue(issues, catalog, "<file>", "<file>", f"catalog file is missing: {path}")
        return None
    except (OSError, UnicodeError) as error:
        _add_issue(issues, catalog, "<file>", "<file>", f"catalog file could not be read: {error}")
        return None

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as error:
        _add_issue(
            issues,
            catalog,
            "<file>",
            "<json>",
            f"malformed JSON at line {error.lineno}, column {error.colno}: {error.msg}",
        )
        return None

    if not isinstance(data, list):
        _add_issue(
            issues,
            catalog,
            "<root>",
            "<root>",
            f"expected a JSON array, got {type(data).__name__}",
        )
        return None

    return data


def _validate_value(issues, catalog, record_number, record, field, expected_type, required=True):
    if field not in record:
        if required:
            _add_issue(issues, catalog, record_number, field, "required field is missing")
        return None, not required

    value = record[field]
    if expected_type is int:
        valid_type = isinstance(value, int) and not isinstance(value, bool)
    else:
        valid_type = isinstance(value, expected_type)

    if not valid_type:
        _add_issue(
            issues,
            catalog,
            record_number,
            field,
            f"expected {expected_type.__name__}, got {type(value).__name__}",
        )
        return None, False

    if expected_type is str and not value.strip():
        _add_issue(issues, catalog, record_number, field, "must not be empty")
        return None, False

    return value, True


def _validate_audio_path(issues, catalog, record_number, field, value, project_root):
    candidate = Path(value)
    if candidate.is_absolute() or PureWindowsPath(value).is_absolute():
        _add_issue(
            issues,
            catalog,
            record_number,
            field,
            "must be relative to the repository root; absolute paths are not allowed",
        )
        return False

    root = Path(project_root).resolve()
    resolved = (root / candidate).resolve()
    if not resolved.is_relative_to(root):
        _add_issue(
            issues,
            catalog,
            record_number,
            field,
            "resolves outside the repository root",
        )
        return False

    extension = Path(value).suffix.lower()
    if extension not in SUPPORTED_AUDIO_EXTENSIONS:
        shown_extension = extension or "<none>"
        supported = ", ".join(sorted(SUPPORTED_AUDIO_EXTENSIONS))
        _add_issue(
            issues,
            catalog,
            record_number,
            field,
            f"unsupported audio extension '{shown_extension}'; expected one of: {supported}",
        )
        return False

    if not resolved.is_file():
        _add_issue(
            issues,
            catalog,
            record_number,
            field,
            f"referenced audio file does not exist: {resolved}",
        )

    return True


def _validate_id(issues, catalog, record_number, record, seen_ids, required):
    record_id, valid = _validate_value(
        issues,
        catalog,
        record_number,
        record,
        "id",
        int,
        required=required,
    )
    if not valid or record_id is None:
        return record_id, valid

    if record_id in seen_ids:
        _add_issue(
            issues,
            catalog,
            record_number,
            "id",
            f"duplicate ID {record_id}; first used by record {seen_ids[record_id]}",
        )
    else:
        seen_ids[record_id] = record_number
    return record_id, valid


def _record_object(raw_record, catalog, record_number, issues):
    if isinstance(raw_record, dict):
        return raw_record
    _add_issue(
        issues,
        catalog,
        record_number,
        "<record>",
        f"expected an object, got {type(raw_record).__name__}",
    )
    return None


def _parse_songs(data, project_root, issues):
    songs = []
    seen_ids = {}
    for record_number, raw_record in enumerate(data or (), start=1):
        record = _record_object(raw_record, CatalogName.SONGS, record_number, issues)
        if record is None:
            continue

        record_id, id_valid = _validate_id(
            issues,
            CatalogName.SONGS,
            record_number,
            record,
            seen_ids,
            required=True,
        )
        track, track_valid = _validate_value(
            issues, CatalogName.SONGS, record_number, record, "track", str
        )
        artist, artist_valid = _validate_value(
            issues, CatalogName.SONGS, record_number, record, "artist", str
        )
        if track_valid:
            _validate_audio_path(
                issues,
                CatalogName.SONGS,
                record_number,
                "track",
                track,
                project_root,
            )

        if id_valid and track_valid and artist_valid:
            songs.append(Song(id=record_id, track=track, artist=artist))
    return songs


def _parse_announcements(data, catalog, media_field, record_type, project_root, issues):
    records = []
    relationship_records = []
    seen_ids = {}
    for record_number, raw_record in enumerate(data or (), start=1):
        record = _record_object(raw_record, catalog, record_number, issues)
        if record is None:
            continue

        record_id, id_valid = _validate_id(
            issues,
            catalog,
            record_number,
            record,
            seen_ids,
            required=False,
        )
        artist, artist_valid = _validate_value(
            issues, catalog, record_number, record, "artist", str
        )
        media_path, media_valid = _validate_value(
            issues, catalog, record_number, record, media_field, str
        )
        song, song_valid = _validate_value(
            issues,
            catalog,
            record_number,
            record,
            "song",
            str,
            required=False,
        )

        if media_valid:
            _validate_audio_path(
                issues, catalog, record_number, media_field, media_path, project_root
            )
        song_path_valid = True
        if song is not None and song_valid:
            song_path_valid = _validate_audio_path(
                issues, catalog, record_number, "song", song, project_root
            )

        if id_valid and artist_valid and media_valid and song_valid:
            parsed_record = record_type(
                artist=artist,
                **{media_field: media_path},
                song=song,
                id=record_id,
            )
            records.append(parsed_record)
            if song_path_valid:
                relationship_records.append((record_number, parsed_record))
    return records, relationship_records


def _parse_ads(data, catalog, media_field, record_type, project_root, issues):
    records = []
    seen_ids = {}
    for record_number, raw_record in enumerate(data or (), start=1):
        record = _record_object(raw_record, catalog, record_number, issues)
        if record is None:
            continue

        record_id, id_valid = _validate_id(
            issues,
            catalog,
            record_number,
            record,
            seen_ids,
            required=False,
        )
        media_path, media_valid = _validate_value(
            issues, catalog, record_number, record, media_field, str
        )
        if media_valid:
            _validate_audio_path(
                issues, catalog, record_number, media_field, media_path, project_root
            )

        if id_valid and media_valid:
            records.append(record_type(**{media_field: media_path}, id=record_id))
    return records


def _validate_song_relationships(songs, relationship_records, catalog, issues):
    songs_by_track = {song.track: song for song in songs}
    for record_number, announcement in relationship_records:
        if announcement.song is None:
            continue

        song = songs_by_track.get(announcement.song)
        if song is None:
            _add_issue(
                issues,
                catalog,
                record_number,
                "song",
                f"references unknown song '{announcement.song}'",
            )
        elif announcement.artist != song.artist:
            _add_issue(
                issues,
                catalog,
                record_number,
                "artist",
                f"artist '{announcement.artist}' does not match song artist "
                f"'{song.artist}' for '{announcement.song}'",
            )


def load_catalogs(project_root=None):
    """Load every runtime catalog or raise one aggregated validation error."""

    root = PROJECT_ROOT if project_root is None else Path(project_root)
    issues = []
    raw_catalogs = {
        catalog: _load_json(catalog, root, issues)
        for catalog in CatalogName
    }

    songs = _parse_songs(raw_catalogs[CatalogName.SONGS], root, issues)
    intros, intro_relationships = _parse_announcements(
        raw_catalogs[CatalogName.INTROS],
        CatalogName.INTROS,
        "intro",
        Intro,
        root,
        issues,
    )
    outros, outro_relationships = _parse_announcements(
        raw_catalogs[CatalogName.OUTROS],
        CatalogName.OUTROS,
        "outro",
        Outro,
        root,
        issues,
    )
    ads = _parse_ads(
        raw_catalogs[CatalogName.ADS],
        CatalogName.ADS,
        "ad",
        Ad,
        root,
        issues,
    )
    ad_intros = _parse_ads(
        raw_catalogs[CatalogName.AD_INTROS],
        CatalogName.AD_INTROS,
        "ad_intro",
        AdIntro,
        root,
        issues,
    )

    if raw_catalogs[CatalogName.SONGS] is not None:
        _validate_song_relationships(
            songs, intro_relationships, CatalogName.INTROS, issues
        )
        _validate_song_relationships(
            songs, outro_relationships, CatalogName.OUTROS, issues
        )

    if issues:
        raise CatalogValidationError(issues)

    return Catalogs(
        songs=tuple(songs),
        intros=tuple(intros),
        outros=tuple(outros),
        ads=tuple(ads),
        ad_intros=tuple(ad_intros),
    )
