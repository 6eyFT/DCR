"""Pygame-backed media duration lookup for the local player."""

import pygame

from catalog_loader import resolve_project_path


class PygameDurationProvider:
    """Load and cache durations through pygame's existing decoder support."""

    def __init__(self):
        self._cache = {}

    def __call__(self, media_path: str) -> float:
        if media_path not in self._cache:
            resolved_path = resolve_project_path(media_path)
            self._cache[media_path] = pygame.mixer.Sound(
                str(resolved_path)
            ).get_length()
        return self._cache[media_path]
