"""Tests for Pydantic model validation."""

import pytest
from pydantic import ValidationError

from aetherdm.models import (
    ActionEntry,
    ActionPool,
    Character,
    Connection,
    Effect,
    Environment,
    Event,
    LocationNode,
)


class TestLocationNode:
    def test_minimal_location(self):
        loc = LocationNode(id="test", name="Test Location")
        assert loc.id == "test"
        assert loc.name == "Test Location"
        assert loc.tags == []
        assert loc.connections == []
        assert loc.last_mutated_round == 0

    def test_location_with_connections(self):
        loc = LocationNode(
            id="village",
            name="Village",
            connections=[
                Connection(target_id="forest", type="path", travel_time=2, propagation_modifier=0.8)
            ],
        )
        assert len(loc.connections) == 1
        assert loc.connections[0].target_id == "forest"


class TestCharacter:
    def test_minimal_character(self):
        ch = Character(id="hero", name="Hero", type="pc", location_id="village")
        assert ch.id == "hero"
        assert ch.type == "pc"
        assert ch.quickness == 5
        assert ch.conditions == []

    def test_npc_creation(self):
        npc = Character(
            id="merchant",
            name="Garrick",
            type="npc",
            location_id="marketplace",
            quickness=3,
            conditions=["panicked"],
        )
        assert npc.type == "npc"
        assert "panicked" in npc.conditions


class TestActionPool:
    def test_new_pool_is_open(self):
        pool = ActionPool(location_id="village", round=1)
        assert pool.status == "open"
        assert pool.actions == []

    def test_add_actions(self):
        pool = ActionPool(
            location_id="market",
            round=2,
            actions=[
                ActionEntry(character_id="hero", intent="Fight the fire", declared_order=1),
                ActionEntry(character_id="merchant", intent="Save grain", declared_order=2),
            ],
        )
        assert len(pool.actions) == 2
        assert pool.actions[0].character_id == "hero"


class TestEffect:
    def test_effect_creation(self):
        effect = Effect(
            target_type="location",
            target_id="village",
            changes={"conditions": ["on_fire"]},
            description="Fire spreads to the village square",
        )
        assert effect.target_type == "location"
        assert effect.changes["conditions"] == ["on_fire"]


class TestEvent:
    def test_event_with_effects(self):
        event = Event(
            id="evt_1",
            round=1,
            origin_location_id="market",
            actor_id="world",
            type="mutation",
            scope="local",
            intensity=8.0,
        )
        assert event.intensity == 8.0
        assert event.effects == []
