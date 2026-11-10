"""Tests for seed loading and repository persistence."""

import json
import tempfile
from pathlib import Path

import pytest

from aetherdm.db.repository import Repository
from aetherdm.seed_loader import SeedLoader


@pytest.fixture()
def repo(tmp_path: Path):
    """Create a temporary repository."""
    db_path = tmp_path / "test.db"
    r = Repository(db_path)
    r.connect()
    yield r
    r.close()


@pytest.fixture()
def sample_seed(tmp_path: Path) -> Path:
    """Create a minimal valid seed file."""
    seed_data = {
        "name": "test_world",
        "description": "A test world",
        "global_flags": {},
        "locations": [
            {
                "id": "town",
                "name": "Test Town",
                "description": "A small test town",
                "tags": ["test", "urban"],
                "environment": {"conditions": [], "objects": [], "resources": {}, "flags": {}},
                "connections": [
                    {"target_id": "forest", "type": "path", "travel_time": 1, "propagation_modifier": 1.0}
                ],
                "characters": [],
                "pending_effects": []
            },
            {
                "id": "forest",
                "name": "Dark Forest",
                "description": "A spooky forest",
                "tags": ["test", "wilderness"],
                "environment": {"conditions": ["dark"], "objects": [], "resources": {}, "flags": {}},
                "connections": [],
                "characters": [],
                "pending_effects": []
            }
        ],
        "characters": [
            {
                "id": "hero",
                "name": "Test Hero",
                "type": "pc",
                "location_id": "town",
                "stats": {"str": 10, "dex": 12},
                "inventory": [],
                "personality": "Brave and curious",
                "goals": ["Explore the forest"],
                "secrets": [],
                "quickness": 6,
                "memory": [],
                "relationships": {},
                "conditions": []
            }
        ]
    }
    seed_path = tmp_path / "test_seed.json"
    seed_path.write_text(json.dumps(seed_data), encoding="utf-8")
    return seed_path


class TestSeedLoader:
    def test_load_seed(self, repo: Repository, sample_seed: Path):
        loader = SeedLoader(repo)
        data = loader.load(sample_seed)
        assert data["name"] == "test_world"

        # Verify persistence
        locs = repo.load_all_locations()
        assert len(locs) == 2
        chars = repo.load_all_characters()
        assert len(chars) == 1
        assert chars[0].name == "Test Hero"

    def test_validate_missing_key(self, repo: Repository, tmp_path: Path):
        bad_seed = tmp_path / "bad.json"
        bad_seed.write_text('{"name": "test"}', encoding="utf-8")
        loader = SeedLoader(repo)
        with pytest.raises(ValueError, match="Seed validation failed"):
            loader.load(bad_seed)

    def test_village_fire_seed(self, repo: Repository):
        """Test loading the actual village_fire seed."""
        seed_path = Path(__file__).parent.parent / "seeds" / "worlds" / "village_fire.json"
        if not seed_path.exists():
            pytest.skip("village_fire.json not found")
        loader = SeedLoader(repo)
        data = loader.load(seed_path)
        assert data["name"] == "village_fire"
        assert len(data["locations"]) == 4
        assert len(data["characters"]) == 4
