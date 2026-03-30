import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent


def resolve_project_path(path):
    candidate = Path(path)
    if candidate.is_absolute():
        return candidate
    return PROJECT_ROOT / candidate


def asset_exists(path):
    return resolve_project_path(path).exists()


def load_data(path):
    file_path = resolve_project_path(path)
    with file_path.open("r", encoding="utf-8") as file:
        return json.load(file)
