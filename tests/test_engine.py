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

    eng = SimulationEngine(repo, use_llm=False)
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


class TestEngineBackgroundBaresexp:
    """Test that background locations store baresexp, not narrative text."""

    def test_background_stores_baresexp(self, engine: SimulationEngine):
        engine.next_round()
        pool = engine.create_pool("town")
        engine.add_action(pool, "hero", "Help the villagers")
        engine.lock_pool("town")

        # Resolve as background (pc_location_id different from pool location)
        effects = engine.resolve_pool(pool, pc_location_id="other_location")

        assert pool.status == "resolved"
        # Background should have baresexp stored
        assert "town" in engine._location_baresexp
        baresexp_str = engine._location_baresexp["town"]
        assert "(task" in baresexp_str or "(pool" in baresexp_str

    def test_pc_location_clears_baresexp(self, engine: SimulationEngine):
        engine.next_round()
        pool = engine.create_pool("town")
        engine.add_action(pool, "hero", "Help the villagers")
        engine.lock_pool("town")

        # First resolve as background
        engine.resolve_pool(pool, pc_location_id="other_location")
        assert "town" in engine._location_baresexp

        # Now resolve as PC location — baresexp should be cleared
        pool2 = engine.create_pool("town")
        engine.add_action(pool2, "hero", "Look around")
        engine.lock_pool("town")
        engine.resolve_pool(pool2, pc_location_id="town")

        assert "town" not in engine._location_baresexp

    def test_get_background_summary_returns_baresexp(self, engine: SimulationEngine):
        engine.next_round()
        pool = engine.create_pool("town")
        engine.add_action(pool, "hero", "Help")
        engine.lock_pool("town")
        engine.resolve_pool(pool, pc_location_id="other_location")

        summary = engine.get_background_summary()
        assert "town" in summary
        assert "(no background activity)" not in summary

    def test_empty_background_summary(self, engine: SimulationEngine):
        summary = engine.get_background_summary()
        assert summary == "(no background activity)"


class TestEngineTransitionNarration:
    """Test narration when PC arrives at a location with baresexp history."""

    def test_narrate_transition_with_baresexp(self, engine: SimulationEngine):
        engine.next_round()
        pool = engine.create_pool("town")
        engine.add_action(pool, "hero", "Help the villagers")
        engine.lock_pool("town")

        # Resolve as background first
        engine.resolve_pool(pool, pc_location_id="other_location")
        assert "town" in engine._location_baresexp

        # Narrate transition
        narrative = engine.narrate_transition("town")
        assert narrative is not None
        assert isinstance(narrative, str)

        # Baresexp should be consumed
        assert "town" not in engine._location_baresexp

    def test_narrate_transition_no_baresexp(self, engine: SimulationEngine):
        narrative = engine.narrate_transition("town")
        assert narrative is None

    def test_transition_narrative_consumed(self, engine: SimulationEngine):
        engine.next_round()
        pool = engine.create_pool("town")
        engine.add_action(pool, "hero", "Help")
        engine.lock_pool("town")
        engine.resolve_pool(pool, pc_location_id="other_location")

        # First call consumes
        narrative1 = engine.narrate_transition("town")
        assert narrative1 is not None

        # Second call returns None (consumed)
        narrative2 = engine.narrate_transition("town")
        assert narrative2 is None

    def test_get_transition_narrative(self, engine: SimulationEngine):
        engine._transition_narratives["town"] = "Something happened here."
        narrative = engine.get_transition_narrative("town")
        assert narrative == "Something happened here."
        # Should be consumed
        assert engine.get_transition_narrative("town") is None
