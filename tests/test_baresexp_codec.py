"""Tests for BareSexpDocument-based DM prompt building."""

import pytest
from baresexp import BareSexpDocument

from aetherdm.baresexp_codec import build_dm_document, build_dm_prompt, DMPromptParts, _count_tokens
from aetherdm.models import ActionPool, LocationNode, Character, Environment, ActionEntry


@pytest.fixture
def sample_location():
    return LocationNode(
        id="marketplace",
        name="Marketplace",
        description="A bustling market area now engulfed in flames.",
        tags=["urban", "market", "dangerous"],
        environment=Environment(conditions=["on_fire", "smoky", "chaotic"]),
        connections=[],
        characters=["npc_garrick", "pc_1"],
    )


@pytest.fixture
def sample_pool():
    pool = ActionPool(location_id="marketplace", round=1)
    pool.actions = [
        ActionEntry(character_id="npc_garrick", intent="Save my grain stall", declared_order=1),
        ActionEntry(character_id="pc_1", intent="Fight the fire with water buckets", declared_order=2, focused=True),
    ]
    pool.status = "locked"
    return pool


@pytest.fixture
def sample_characters():
    return [
        Character(
            id="npc_garrick", name="Garrick", type="npc", location_id="marketplace",
            personality="Gruff merchant, cares about his goods.", goals=["Save grain"],
            quickness=3, conditions=["panicked"],
        ),
        Character(
            id="pc_1", name="Ko Toke Kyi", type="pc", location_id="marketplace",
            personality="Brave but cautious.", goals=["Contain the fire"],
            quickness=6, conditions=[],
        ),
    ]


class TestBuildDMDocument:
    def test_returns_dm_prompt_parts(self, sample_pool, sample_location, sample_characters):
        prompt = build_dm_document(sample_pool, sample_location, sample_characters)
        assert isinstance(prompt, DMPromptParts)
        assert isinstance(prompt.document, BareSexpDocument)
        assert prompt.token_count > 0
        assert prompt.system_msg
        assert prompt.user_msg

    def test_user_msg_contains_raw_encoded_state(self, sample_pool, sample_location, sample_characters):
        prompt = build_dm_document(sample_pool, sample_location, sample_characters)
        assert ";; Raw encoded state" in prompt.user_msg
        # Minimal mode shortens identifiers but key references remain
        assert "location" in prompt.user_msg
        assert "marketplace" in prompt.user_msg
        assert "npc-garrick" in prompt.user_msg or "garrick" in prompt.user_msg

    def test_system_msg_contains_constraints(self, sample_pool, sample_location, sample_characters):
        prompt = build_dm_document(sample_pool, sample_location, sample_characters)
        assert "resolved-actions" in prompt.system_msg.lower() or "json-keys" in prompt.system_msg.lower()

    def test_baresexp_output_format_changes_constraints(self, sample_pool, sample_location, sample_characters):
        prompt_json = build_dm_document(sample_pool, sample_location, sample_characters, output_format="json")
        prompt_bsexp = build_dm_document(sample_pool, sample_location, sample_characters, output_format="baresexp")
        assert "json" in prompt_json.system_msg.lower()
        assert "baresexp" in prompt_bsexp.system_msg.lower()

    def test_empty_characters(self, sample_pool, sample_location):
        prompt = build_dm_document(sample_pool, sample_location, [])
        assert "no-characters-at" in prompt.system_msg.lower() or "no characters" in prompt.system_msg.lower()
        assert prompt.token_count > 0

    def test_empty_pool_actions(self, sample_location, sample_characters):
        pool = ActionPool(location_id="marketplace", round=1)
        prompt = build_dm_document(pool, sample_location, sample_characters)
        assert prompt.token_count > 0


class TestBuildDMPromptLegacy:
    def test_legacy_still_works(self, sample_pool, sample_location, sample_characters):
        combined, token_count = build_dm_prompt(sample_pool, sample_location, sample_characters)
        assert isinstance(combined, str)
        assert token_count > 0
        assert "(context" in combined
        assert "(task" in combined
