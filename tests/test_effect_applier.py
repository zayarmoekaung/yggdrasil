"""Tests for effect applier."""

import json
import tempfile
from pathlib import Path

import pytest

from aetherdm.db.repository import Repository
from aetherdm.models import Character, Effect, LocationNode
from aetherdm.simulation.effect_applier import apply_effect


@pytest.fixture()
def repo(tmp_path: Path):
    db_path = tmp_path / "test.db"
    r = Repository(db_path)
    r.connect()
    yield r
    r.close()


@pytest.fixture()
def sample_location():
    return LocationNode(
        id="town",
        name="Test Town",
        tags=["urban"],
    )


@pytest.fixture()
def sample_character():
    return Character(
        id="hero",
        name="Hero",
        type="pc",
        location_id="town",
        conditions=[],
    )


class TestApplyEffect:
    def test_apply_location_condition_change(self, repo: Repository, sample_location: LocationNode):
        repo.save_location(sample_location)
        locations = {"town": sample_location}
        characters = {}

        effect = Effect(
            target_type="location",
            target_id="town",
            changes={"environment": {"conditions": ["on_fire"]}},
            description="Fire starts in town",
        )
        apply_effect(effect, repo, locations, characters)

        # Verify in-memory change
        assert "on_fire" in locations["town"].environment.conditions

        # Verify persisted change
        reloaded = repo.load_location("town")
        assert reloaded is not None
        assert "on_fire" in reloaded.environment.conditions

    def test_apply_character_condition_change(self, repo: Repository, sample_character: Character):
        repo.save_character(sample_character)
        locations = {}
        characters = {"hero": sample_character}

        effect = Effect(
            target_type="character",
            target_id="hero",
            changes={"conditions": ["wounded"]},
            description="Hero gets wounded",
        )
        apply_effect(effect, repo, locations, characters)

        # Verify in-memory change
        assert "wounded" in characters["hero"].conditions

        # Verify persisted change
        reloaded = repo.load_character("hero")
        assert reloaded is not None
        assert "wounded" in reloaded.conditions

    def test_apply_effect_to_nonexistent_target(self, repo: Repository):
        locations = {}
        characters = {}

        effect = Effect(
            target_type="location",
            target_id="nonexistent",
            changes={"environment": {"conditions": ["flooded"]}},
            description="Should be ignored",
        )
        # Should not raise
        apply_effect(effect, repo, locations, characters)

    def test_apply_world_effect_noop(self, repo: Repository):
        locations = {}
        characters = {}

        effect = Effect(
            target_type="world",
            target_id="world",
            changes={"global_flags": {"crisis_active": True}},
            description="World-level effect",
        )
        # Should not raise (world effects are logged but not persisted in Phase 1)
        apply_effect(effect, repo, locations, characters)

    def test_apply_edge_effect(self, repo: Repository, sample_location: LocationNode):
        from aetherdm.models import Connection

        loc = LocationNode(
            id="town",
            name="Test Town",
            connections=[
                Connection(target_id="forest", type="path", travel_time=2, propagation_modifier=1.0)
            ],
        )
        repo.save_location(loc)
        locations = {"town": loc}
        characters = {}

        effect = Effect(
            target_type="edge",
            target_id="town->forest",
            changes={
                "from_id": "town",
                "to_id": "forest",
                "propagation_modifier": 0.5,
            },
            description="Road blocked, propagation reduced",
        )
        apply_effect(effect, repo, locations, characters)

        # Verify change
        reloaded = repo.load_location("town")
        assert reloaded is not None
        assert reloaded.connections[0].propagation_modifier == 0.5
