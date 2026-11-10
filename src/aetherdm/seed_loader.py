"""Seed loader — loads world seeds from JSON files into the repository."""

import json
from pathlib import Path

from pydantic import ValidationError

from aetherdm.db.repository import Repository
from aetherdm.models import Character, LocationNode
from aetherdm.models.seed import SeedWorld
from aetherdm.seed_validator import validate_seed_data


class SeedLoader:
    """Loads a world seed JSON file and populates the repository."""

    def __init__(self, repo: Repository):
        self.repo = repo

    def load(self, seed_path: Path | str) -> dict:
        """Load a seed file and persist all locations and characters to the repository."""
        seed_path = Path(seed_path)
        with open(seed_path, "r", encoding="utf-8") as f:
            seed_data = json.load(f)

        # Validate with Pydantic models + cross-reference checks
        seed, errors = validate_seed_data(seed_data)
        if errors:
            error_msgs = "\n".join(f"  - {e}" for e in errors)
            raise ValueError(f"Seed validation failed:\n{error_msgs}")

        self._persist_seed(seed_data)
        return seed_data

    def _persist_seed(self, data: dict) -> None:
        """Save all locations and characters from the seed to the repository."""
        for loc_data in data["locations"]:
            location = LocationNode(**loc_data)
            self.repo.save_location(location)

        for char_data in data["characters"]:
            character = Character(**char_data)
            self.repo.save_character(character)
