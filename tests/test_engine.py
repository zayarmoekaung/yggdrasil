"""Tests for the simulation engine (rule-based DM)."""

import json
import tempfile
from pathlib import Path

import pytest

from aetherdm.db.repository import Repository
from aetherdm.models import Character, LocationNode
from aetherdm.simulation.engine import SimulationEngine


@pytest.fixture()
def engine(tmp_path: Path):
    db_path = tmp_path / "test.db"
    repo = Repository(db_path)
    repo.connect()

    # Set up a minimal test world
    loc = LocationNode(
        id="town",
        name="Test Town",
        tags=["urban"],
        characters=["hero", "villain"],
    )
    repo.save_location(loc)

    hero = Character(
        id="hero",
        name="Hero",
        type="pc",
        location_id="town",
        quickness=8,
        goals=["Save the town"],
    )
    repo.save_character(hero)

    villain = Character(
        id="villain",
        name="Villain",
        type="npc",
        location_id="town",
        quickness=5,
        goals=["Destroy the town"],
    )
    repo.save_character(villain)

    eng = SimulationEngine(repo)
    eng._load_world_state()
    yield eng

    repo.close()


class TestSimulationEngine:
    def test_next_round_increments(self, engine: SimulationEngine):
        assert engine.current_round == 0
        r = engine.next_round()
        assert r == 1
        assert engine.current_round == 1

    def test_create_pool(self, engine: SimulationEngine):
        engine.next_round()
        pool = engine.create_pool("town")
        assert pool.location_id == "town"
        assert pool.round == 1
        assert pool.status == "open"

    def test_add_action(self, engine: SimulationEngine):
        engine.next_round()
        pool = engine.create_pool("town")
        engine.add_action(pool, "hero", "Save the town")
        assert len(pool.actions) == 1
        assert pool.actions[0].character_id == "hero"

    def test_lock_pool(self, engine: SimulationEngine):
        engine.next_round()
        pool = engine.create_pool("town")
        locked = engine.lock_pool("town")
        assert locked is not None
        assert locked.status == "locked"

    def test_resolve_independent_actions(self, engine: SimulationEngine):
        """Independent actions should both succeed."""
        engine.next_round()
        pool = engine.create_pool("town")
        engine.add_action(pool, "hero", "Help the villagers")
        engine.add_action(pool, "villain", "Gather supplies")
        engine.lock_pool("town")

        effects = engine.resolve_pool(pool)
        # Both actions are independent, so both succeed
        assert len(effects) == 2
        assert pool.status == "resolved"

    def test_resolve_contradictory_actions(self, engine: SimulationEngine):
        """Phase 1: all actions succeed — contradiction detection is deferred to LLM DM in Phase 2."""
        engine.next_round()
        pool = engine.create_pool("town")
        engine.add_action(pool, "hero", "Protect the town")
        engine.add_action(pool, "villain", "Destroy the town")
        engine.lock_pool("town")

        effects = engine.resolve_pool(pool)
        # Phase 1: both actions succeed (no contradiction detection)
        assert len(effects) == 2
        assert pool.status == "resolved"

        # Both characters should have "acted" condition
        hero = engine._characters["hero"]
        villain = engine._characters["villain"]
        assert "acted" in hero.conditions
        assert "acted" in villain.conditions

    def test_resolve_with_ineligible_character(self, engine: SimulationEngine):
        """Ineligible characters should not have their actions resolved."""
        engine.next_round()
        pool = engine.create_pool("town")

        # Make hero ineligible
        hero = engine._characters["hero"]
        hero.conditions.append("unconscious")
        engine.repo.save_character(hero)

        engine.add_action(pool, "hero", "Save the town")
        engine.add_action(pool, "villain", "Destroy the town")
        engine.lock_pool("town")

        effects = engine.resolve_pool(pool)
        # Only villain's action should resolve
        assert len(effects) == 1

    def test_get_narrative(self, engine: SimulationEngine):
        engine.next_round()
        pool = engine.create_pool("town")
        from aetherdm.models import Effect

        effects = [Effect(target_type="character", target_id="hero", changes={}, description="Hero acted")]
        narrative = engine.get_narrative(pool, effects)
        assert "Round 1" in narrative
        assert "Hero acted" in narrative
