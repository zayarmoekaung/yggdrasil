"""Tests for Phase 4: seed validation, export, and component loading."""

import json
from pathlib import Path

import pytest

from aetherdm.component_seed_loader import ComponentSeedLoader
from aetherdm.db.repository import Repository
from aetherdm.models.seed import SeedCharacter, SeedLocation, SeedWorld
from aetherdm.seed_exporter import export_seed, export_seed_to_file
from aetherdm.seed_loader import SeedLoader
from aetherdm.seed_validator import SeedValidationError, validate_seed, validate_seed_data


@pytest.fixture()
def repo(tmp_path: Path):
    """Create a temporary repository."""
    db_path = tmp_path / "test.db"
    r = Repository(db_path)
    r.connect()
    yield r
    r.close()


@pytest.fixture()
def valid_seed_dict() -> dict:
    """A minimal valid seed dict."""
    return {
        "name": "test_world",
        "description": "A test world",
        "global_flags": {},
        "locations": [
            {
                "id": "town",
                "name": "Test Town",
                "description": "A test town",
                "tags": ["test"],
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
                "description": "A dark forest",
                "tags": ["wild"],
                "environment": {"conditions": ["dark"], "objects": [], "resources": {}, "flags": {}},
                "connections": [],
                "characters": [],
                "pending_effects": []
            }
        ],
        "characters": [
            {
                "id": "hero",
                "name": "Hero",
                "type": "pc",
                "location_id": "town",
                "stats": {"str": 10},
                "inventory": [],
                "personality": "Brave",
                "goals": ["Explore"],
                "secrets": [],
                "quickness": 6,
                "memory": [],
                "relationships": {},
                "conditions": []
            }
        ]
    }


# ── SeedWorld Pydantic model tests ──

class TestSeedWorldModel:
    def test_valid_minimal_seed(self):
        data = {
            "name": "x",
            "locations": [{"id": "a", "name": "A"}],
            "characters": [{"id": "c", "name": "C", "type": "npc", "location_id": "a"}],
        }
        seed = SeedWorld(**data)
        assert seed.name == "x"
        assert len(seed.locations) == 1
        assert len(seed.characters) == 1

    def test_invalid_connection_type(self):
        data = {
            "name": "x",
            "locations": [
                {
                    "id": "a", "name": "A",
                    "connections": [{"target_id": "b", "type": "invalid", "travel_time": 1, "propagation_modifier": 1.0}]
                }
            ],
            "characters": [{"id": "c", "name": "C", "type": "npc", "location_id": "a"}],
        }
        with pytest.raises(Exception):  # Pydantic ValidationError
            SeedWorld(**data)

    def test_invalid_character_type(self):
        data = {
            "name": "x",
            "locations": [{"id": "a", "name": "A"}],
            "characters": [{"id": "c", "name": "C", "type": "monster", "location_id": "a"}],
        }
        with pytest.raises(Exception):
            SeedWorld(**data)

    def test_relationship_out_of_range(self):
        data = {
            "name": "x",
            "locations": [{"id": "a", "name": "A"}],
            "characters": [
                {"id": "c1", "name": "C1", "type": "npc", "location_id": "a"},
                {"id": "c2", "name": "C2", "type": "npc", "location_id": "a", "relationships": {"c1": 200}},
            ],
        }
        with pytest.raises(Exception):
            SeedWorld(**data)

    def test_quickness_bounds(self):
        data = {
            "name": "x",
            "locations": [{"id": "a", "name": "A"}],
            "characters": [{"id": "c", "name": "C", "type": "npc", "location_id": "a", "quickness": 0}],
        }
        with pytest.raises(Exception):
            SeedWorld(**data)


# ── Seed validator tests ──

class TestValidateSeed:
    def test_valid_seed(self, valid_seed_dict, tmp_path):
        p = tmp_path / "valid.json"
        p.write_text(json.dumps(valid_seed_dict), encoding="utf-8")
        seed, errors = validate_seed(p)
        assert seed is not None
        assert len(errors) == 0

    def test_missing_required_fields(self, tmp_path):
        p = tmp_path / "bad.json"
        p.write_text('{"name": "x"}', encoding="utf-8")
        seed, errors = validate_seed(p)
        assert seed is None
        assert len(errors) >= 2  # locations and characters are missing

    def test_invalid_json(self, tmp_path):
        p = tmp_path / "bad.json"
        p.write_text("not json", encoding="utf-8")
        seed, errors = validate_seed(p)
        assert seed is None
        assert len(errors) == 1
        assert errors[0].field == "json"

    def test_file_not_found(self):
        seed, errors = validate_seed("/nonexistent/path.json")
        assert seed is None
        assert len(errors) == 1
        assert errors[0].field == "file"


# ── Cross-reference validation tests ──

class TestCrossRefValidation:
    def test_character_references_missing_location(self, valid_seed_dict, tmp_path):
        valid_seed_dict["characters"][0]["location_id"] = "nonexistent"
        p = tmp_path / "bad.json"
        p.write_text(json.dumps(valid_seed_dict), encoding="utf-8")
        seed, errors = validate_seed(p)
        assert seed is not None
        assert any("nonexistent" in str(e) for e in errors)

    def test_connection_references_missing_location(self, valid_seed_dict, tmp_path):
        valid_seed_dict["locations"][0]["connections"][0]["target_id"] = "nowhere"
        p = tmp_path / "bad.json"
        p.write_text(json.dumps(valid_seed_dict), encoding="utf-8")
        seed, errors = validate_seed(p)
        assert seed is not None
        assert any("nowhere" in str(e) for e in errors)

    def test_relationship_references_missing_character(self, valid_seed_dict, tmp_path):
        valid_seed_dict["characters"][0]["relationships"] = {"ghost": 50}
        p = tmp_path / "bad.json"
        p.write_text(json.dumps(valid_seed_dict), encoding="utf-8")
        seed, errors = validate_seed(p)
        assert seed is not None
        assert any("ghost" in str(e) for e in errors)

    def test_location_references_missing_character(self, valid_seed_dict, tmp_path):
        valid_seed_dict["locations"][0]["characters"] = ["missing_char"]
        p = tmp_path / "bad.json"
        p.write_text(json.dumps(valid_seed_dict), encoding="utf-8")
        seed, errors = validate_seed(p)
        assert seed is not None
        assert any("missing_char" in str(e) for e in errors)

    def test_self_connection(self, valid_seed_dict, tmp_path):
        valid_seed_dict["locations"][0]["connections"][0]["target_id"] = "town"
        p = tmp_path / "bad.json"
        p.write_text(json.dumps(valid_seed_dict), encoding="utf-8")
        seed, errors = validate_seed(p)
        assert seed is not None
        assert any("itself" in str(e) for e in errors)

    def test_duplicate_location_ids(self, valid_seed_dict, tmp_path):
        valid_seed_dict["locations"].append({
            "id": "town",  # duplicate
            "name": "Town 2",
        })
        p = tmp_path / "bad.json"
        p.write_text(json.dumps(valid_seed_dict), encoding="utf-8")
        seed, errors = validate_seed(p)
        assert seed is not None
        assert any("duplicate" in str(e) for e in errors)


# ── Seed exporter tests ──

class TestSeedExporter:
    def test_export_and_reload(self, repo, valid_seed_dict):
        # First load a seed
        loader = SeedLoader(repo)
        loader.load_from_dict(valid_seed_dict)

        # Export it
        exported = export_seed(repo, seed_name="exported_test")
        assert exported["name"] == "exported_test"
        assert len(exported["locations"]) == 2
        assert len(exported["characters"]) == 1

    def test_export_to_file(self, repo, valid_seed_dict, tmp_path):
        loader = SeedLoader(repo)
        loader.load_from_dict(valid_seed_dict)

        output = tmp_path / "exported.json"
        export_seed_to_file(repo, output, seed_name="my_export")
        assert output.exists()

        # Verify it's valid
        with open(output, "r", encoding="utf-8") as f:
            data = json.load(f)
        seed, errors = validate_seed_data(data)
        assert seed is not None
        assert len(errors) == 0
        assert seed.name == "my_export"

    def test_export_preserves_state_changes(self, repo, valid_seed_dict, tmp_path):
        """Verify that runtime state changes (e.g., conditions) are preserved in export."""
        loader = SeedLoader(repo)
        loader.load_from_dict(valid_seed_dict)

        # Modify a character's conditions at runtime
        ch = repo.load_character("hero")
        ch.conditions.append("panicked")
        ch.conditions.append("wounded")
        repo.save_character(ch)

        # Export and verify
        output = tmp_path / "modified.json"
        export_seed_to_file(repo, output)
        with open(output, "r", encoding="utf-8") as f:
            data = json.load(f)

        hero = next(c for c in data["characters"] if c["id"] == "hero")
        assert "panicked" in hero["conditions"]
        assert "wounded" in hero["conditions"]


# ── Component seed loader tests ──

class TestComponentSeedLoader:
    def _setup_components(self, tmp_path: Path, valid_seed_dict: dict) -> Path:
        """Create a component directory structure from a seed dict."""
        world_dir = tmp_path / "test_world"
        world_dir.mkdir()

        loader = ComponentSeedLoader(Repository(":memory:"))
        loader.export_components(valid_seed_dict, world_dir)
        return world_dir

    def test_load_components(self, repo, valid_seed_dict, tmp_path):
        world_dir = self._setup_components(tmp_path, valid_seed_dict)

        loader = ComponentSeedLoader(repo)
        seed_data = loader.load(world_dir)

        assert seed_data["name"] == "test_world"
        assert len(seed_data["locations"]) == 2
        assert len(seed_data["characters"]) == 1

        # Verify persistence
        locs = repo.load_all_locations()
        assert len(locs) == 2
        chars = repo.load_all_characters()
        assert len(chars) == 1

    def test_export_and_reload_components(self, repo, valid_seed_dict, tmp_path):
        """Round-trip: export components → load components → verify."""
        world_dir = self._setup_components(tmp_path, valid_seed_dict)

        loader = ComponentSeedLoader(repo)
        seed_data = loader.load(world_dir)

        assert len(seed_data["locations"]) == 2
        assert len(seed_data["characters"]) == 1

    def test_load_missing_directory(self, repo):
        loader = ComponentSeedLoader(repo)
        with pytest.raises(ValueError, match="not found"):
            loader.load("/nonexistent/dir")

    def test_component_directory_structure(self, valid_seed_dict, tmp_path):
        """Verify export_components creates the right files."""
        world_dir = tmp_path / "world"
        loader = ComponentSeedLoader(Repository(":memory:"))
        loader.export_components(valid_seed_dict, world_dir)

        assert (world_dir / "world.json").exists()
        assert (world_dir / "locations" / "town.json").exists()
        assert (world_dir / "locations" / "forest.json").exists()
        assert (world_dir / "pcs" / "hero.json").exists()
        assert not (world_dir / "npcs").exists() or list((world_dir / "npcs").glob("*.json")) == []


# Add load_from_dict helper to SeedLoader for testing
def _load_from_dict(self, data: dict) -> dict:
    """Load a seed from a dict (for testing)."""
    seed, errors = validate_seed_data(data)
    if errors:
        error_msgs = "\n".join(f"  - {e}" for e in errors)
        raise ValueError(f"Seed validation failed:\n{error_msgs}")

    from aetherdm.models import Character, LocationNode
    for loc_data in data["locations"]:
        self.repo.save_location(LocationNode(**loc_data))
    for char_data in data["characters"]:
        self.repo.save_character(Character(**char_data))
    return data


# Monkey-patch for tests
SeedLoader.load_from_dict = _load_from_dict
