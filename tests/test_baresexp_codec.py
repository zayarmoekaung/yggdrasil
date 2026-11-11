"""Tests for BareSexpDocument-based DM prompt building."""

import json
import pytest
from baresexp import BareSexpDocument

from aetherdm.baresexp_codec import build_dm_document, build_narrate_document, build_dm_prompt, DMPromptParts, _count_tokens, _compute_current_state
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

    def test_user_msg_contains_json_payload_in_content(self, sample_pool, sample_location, sample_characters):
        """Task content field should contain JSON data payload (not bare text after the task)."""
        prompt = build_dm_document(sample_pool, sample_location, sample_characters)
        # The content field should contain a JSON object with location, pool, characters
        assert '(content ' in prompt.user_msg
        # Full mode escapes JSON quotes as \\" — check for the escaped form
        assert '\\"location\\"' in prompt.user_msg
        assert '\\"pool\\"' in prompt.user_msg
        assert '\\"characters\\"' in prompt.user_msg
        # Verify the content field contains parseable JSON by extracting it robustly
        # Find the content value between (content " and the closing ")
        import re
        match = re.search(r'\(content "(.+?)"\)\s*\(steps', prompt.user_msg, re.DOTALL)
        if not match:
            match = re.search(r'\(content "(.+?)"\)\s*\)', prompt.user_msg, re.DOTALL)
        assert match, "Could not find (content ...) in user_msg"
        content_str = match.group(1).replace('\\"', '"')
        data = json.loads(content_str)
        assert "location" in data
        assert "pool" in data
        assert "characters" in data
        assert len(data["characters"]) == 2

    def test_user_msg_has_instruction_steps(self, sample_pool, sample_location, sample_characters):
        """Task should have steps describing the resolution pipeline (instructions, not data)."""
        prompt = build_dm_document(sample_pool, sample_location, sample_characters)
        assert "(steps" in prompt.user_msg
        assert "read-payload" in prompt.user_msg
        assert "interpret-intentions" in prompt.user_msg
        assert "emit-effects" in prompt.user_msg
        assert "narrate" in prompt.user_msg

    def test_system_msg_contains_constraints(self, sample_pool, sample_location, sample_characters):
        prompt = build_dm_document(sample_pool, sample_location, sample_characters)
        # Minimal mode shortens text, so check for shortened forms
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


class TestComputeCurrentState:
    def test_with_active_conditions(self):
        loc = LocationNode(
            id="marketplace",
            name="Marketplace",
            description="A bustling market area.",
            environment=Environment(conditions=["on_fire", "smoky", "chaotic"]),
        )
        state = _compute_current_state(loc)
        assert "A bustling market area." in state
        assert "Current state:" in state
        assert "on_fire" in state
        assert "smoky" in state
        assert "chaotic" in state

    def test_without_conditions(self):
        loc = LocationNode(
            id="village_square",
            name="Village Square",
            description="A peaceful gathering place.",
            environment=Environment(conditions=[]),
        )
        state = _compute_current_state(loc)
        assert "A peaceful gathering place." in state
        assert "calm, no notable conditions" in state

    def test_empty_description(self):
        loc = LocationNode(
            id="secret_room",
            name="Secret Room",
            description="",
            environment=Environment(conditions=["dark"]),
        )
        state = _compute_current_state(loc)
        assert "(no description)" in state
        assert "dark" in state


class TestDMDocumentCurrentState:
    def test_payload_includes_current_state(self, sample_pool, sample_location, sample_characters):
        prompt = build_dm_document(sample_pool, sample_location, sample_characters)
        import re
        match = re.search(r'\(content "(.+?)"\)\s*\(steps', prompt.user_msg, re.DOTALL)
        if not match:
            match = re.search(r'\(content "(.+?)"\)\s*\)', prompt.user_msg, re.DOTALL)
        assert match, "Could not find (content ...) in user_msg"
        content_str = match.group(1).replace('\\"', '"')
        data = json.loads(content_str)
        assert "current_state" in data
        assert "on_fire" in data["current_state"]
        assert "smoky" in data["current_state"]

    def test_resolution_constraints_mention_current_state(self, sample_pool, sample_location, sample_characters):
        prompt = build_dm_document(sample_pool, sample_location, sample_characters)
        # Minimal mode condenses constraint text, so check for fragments
        sys_lower = prompt.system_msg.lower()
        assert "stati" in sys_lower  # "current_state" → condensed to "stati"
        assert "payload-includes-both-loca-descrip" in sys_lower  # part of the constraint about description vs current_state


class TestNarrateDocumentConstraints:
    def test_payload_includes_current_state(self, sample_pool, sample_location, sample_characters):
        from aetherdm.models import DMResolution
        resolution = DMResolution(
            resolved_actions=[],
            narrative="The fire was extinguished.",
            world_notes="",
        )
        prompt = build_narrate_document(sample_location, sample_pool, resolution.narrative, [])
        import re
        match = re.search(r'\(content "(.+?)"\)\s*\(steps', prompt.user_msg, re.DOTALL)
        if not match:
            match = re.search(r'\(content "(.+?)"\)\s*\)', prompt.user_msg, re.DOTALL)
        assert match, "Could not find (content ...) in user_msg"
        content_str = match.group(1).replace('\\"', '"')
        data = json.loads(content_str)
        assert "current_state" in data

    def test_constraints_warn_about_round_metadata(self, sample_pool, sample_location, sample_characters):
        from aetherdm.models import DMResolution
        resolution = DMResolution(resolved_actions=[], narrative="Test", world_notes="")
        prompt = build_narrate_document(sample_location, sample_pool, resolution.narrative, [])
        assert "round" in prompt.system_msg.lower()
        assert "never mention round" in prompt.system_msg.lower() or "metadata" in prompt.system_msg.lower()

    def test_constraints_warn_about_current_state(self, sample_pool, sample_location, sample_characters):
        from aetherdm.models import DMResolution
        resolution = DMResolution(resolved_actions=[], narrative="Test", world_notes="")
        prompt = build_narrate_document(sample_location, sample_pool, resolution.narrative, [])
        sys_lower = prompt.system_msg.lower()
        assert "current-state" in sys_lower or "current_state" in sys_lower  # condensed form
        assert "ground-scene" in sys_lower  # "GROUND YOUR SCENE IN current_state" condensed

    def test_no_round_in_facts(self, sample_pool, sample_location, sample_characters):
        """Round number should not appear in context facts (removed to prevent leakage)."""
        from aetherdm.models import DMResolution
        resolution = DMResolution(resolved_actions=[], narrative="Test", world_notes="")
        prompt = build_narrate_document(sample_location, sample_pool, resolution.narrative, [])
        # Check the facts section does NOT contain "Round:" as a standalone fact
        import re
        # The facts section is: (facts (fact ...))
        facts_match = re.search(r'\(facts\s+(.+?)\s*\)', prompt.system_msg, re.DOTALL)
        assert facts_match, "Could not find (facts ...) in system_msg"
        facts_content = facts_match.group(1)
        assert "round" not in facts_content.lower(), f"Round should not appear in facts, but found: {facts_content}"
