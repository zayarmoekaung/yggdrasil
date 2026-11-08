"""Seed loader — loads world seeds from JSON files into the repository."""

import json
from pathlib import Path

from aetherdm.db.repository import Repository
from aetherdm.models import Character, LocationNode


class SeedLoader:
    """Loads a world seed JSON file and populates the repository."""

    def __init__(self, repo: Repository):
        self.repo = repo

    def load(self, seed_path: Path | str) -> dict:
        """Load a seed file and persist all locations and characters to the repository."""
        seed_path = Path(seed_path)
        with open(seed_path, "r", encoding="utf-8") as f:
            seed_data = json.load(f)

        self._validate_seed(seed_data)
        self._persist_seed(seed_data)
        return seed_data

    def _validate_seed(self, data: dict) -> None:
        """Basic validation — ensure required top-level keys exist."""
        required_keys = {"name", "locations", "characters"}
        missing = required_keys - set(data.keys())
        if missing:
            raise ValueError(f"Seed is missing required keys: {missing}")

        # Validate each location has id and name
        for loc in data["locations"]:
            if "id" not in loc or "name" not in loc:
                raise ValueError(f"Location seed missing required fields: {loc}")

        # Validate each character has id, name, type, location_id
        for ch in data["characters"]:
            for field in ("id", "name", "type", "location_id"):
                if field not in ch:
                    raise ValueError(f"Character seed missing required field '{field}': {ch}")

    def _persist_seed(self, data: dict) -> None:
        """Save all locations and characters from the seed to the repository."""
        for loc_data in data["locations"]:
            location = LocationNode(**loc_data)
            self.repo.save_location(location)

        for char_data in data["characters"]:
            character = Character(**char_data)
            self.repo.save_character(character)
