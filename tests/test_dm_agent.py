"""Tests for the DM Agent (LLM-powered and fallback)."""

import json
import pytest

from aetherdm.agents.dm_agent import DMAgent
from aetherdm.models import ActionEntry, ActionPool, Character, DMResolution, Effect, LocationNode


@pytest.fixture()
def dm_agent():
    return DMAgent(llm=None)  # No LLM — tests fallback only


@pytest.fixture()
def sample_pool():
    return ActionPool(
        location_id="marketplace",
        round=1,
        actions=[
            ActionEntry(character_id="npc_garrick", intent="Save his remaining grain", declared_order=1),
            ActionEntry(character_id="npc_mira", intent="Get people to safety", declared_order=2),
        ],
    )


@pytest.fixture()
def sample_location():
    return LocationNode(
        id="marketplace",
        name="Marketplace",
        description="A bustling market area now engulfed in flames.",
        environment={"conditions": ["on_fire", "smoky"], "objects": [], "resources": {}, "flags": {}}.__class__(
            conditions=["on_fire", "smoky"], objects=[], resources={}, flags={}
        ),
        characters=["npc_garrick", "npc_mira"],
    )


@pytest.fixture()
def sample_characters():
    return [
        Character(
            id="npc_garrick", name="Garrick", type="npc", location_id="marketplace",
            quickness=3, conditions=["panicked"],
            personality="Gruff merchant, cares more about his goods.",
            goals=["Save his remaining grain"], secrets=[],
        ),
        Character(
            id="npc_mira", name="Mira", type="npc", location_id="marketplace",
            quickness=8, conditions=["alarmed"],
            personality="Quick-witted weaver. Tries to keep everyone calm.",
            goals=["Get people to safety"], secrets=[],
        ),
    ]


class TestDMAgentFallback:
    def test_fallback_resolves_all_eligible_actions(self, dm_agent, sample_pool, sample_characters):
        resolution = dm_agent._fallback_resolve(sample_pool, sample_characters)
        assert len(resolution.resolved_actions) == 2
        assert all(a.success_level == "success" for a in resolution.resolved_actions)

    def test_fallback_skips_ineligible_characters(self, dm_agent, sample_pool):
        # Make Garrick unconscious (ineligible)
        chars = [
            Character(
                id="npc_garrick", name="Garrick", type="npc", location_id="marketplace",
                quickness=3, conditions=["unconscious"],
                personality="Gruff merchant.", goals=["Save grain"], secrets=[],
            ),
            Character(
                id="npc_mira", name="Mira", type="npc", location_id="marketplace",
                quickness=8, conditions=[],
                personality="Calm weaver.", goals=["Safety"], secrets=[],
            ),
        ]
        resolution = dm_agent._fallback_resolve(sample_pool, chars)
        assert len(resolution.resolved_actions) == 1
        assert resolution.resolved_actions[0].character_id == "npc_mira"

    def test_fallback_produces_narrative(self, dm_agent, sample_pool, sample_characters):
        resolution = dm_agent._fallback_resolve(sample_pool, sample_characters)
        # Narrative includes character names and action intents
        assert "garrick" in resolution.narrative.lower() or "mira" in resolution.narrative.lower()
        assert resolution.world_notes == ""


class TestDMAgentContextBuilding:
    def test_build_context_includes_all_fields(self, dm_agent, sample_pool, sample_location, sample_characters):
        context = dm_agent.build_context(sample_pool, sample_location, sample_characters)
        assert context["location_name"] == "Marketplace"
        assert "on_fire" in context["environment_conditions"]
        assert "npc_garrick" in context["character_context"]
        assert "Save his remaining grain" in context["action_context"]

    def test_build_context_with_empty_actions(self, dm_agent, sample_location, sample_characters):
        empty_pool = ActionPool(location_id="marketplace", round=1)
        context = dm_agent.build_context(empty_pool, sample_location, sample_characters)
        assert "(no actions declared)" in context["action_context"]


class TestDMAgentParsing:
    def test_parse_plain_json(self, dm_agent):
        text = json.dumps({
            "resolved_actions": [],
            "narrative": "Nothing happened.",
            "world_notes": "",
        })
        resolution = dm_agent.parse_llm_response(text)
        assert isinstance(resolution, DMResolution)
        assert resolution.narrative == "Nothing happened."

    def test_parse_markdown_json(self, dm_agent):
        text = """```json
{
  "resolved_actions": [],
  "narrative": "The fire rages on.",
  "world_notes": "Smoke spreads to adjacent areas."
}
```"""
        resolution = dm_agent.parse_llm_response(text)
        assert resolution.narrative == "The fire rages on."
        assert resolution.world_notes == "Smoke spreads to adjacent areas."

    def test_parse_markdown_json_no_language(self, dm_agent):
        text = """```
{
  "resolved_actions": [],
  "narrative": "Quiet night.",
  "world_notes": ""
}
```"""
        resolution = dm_agent.parse_llm_response(text)
        assert resolution.narrative == "Quiet night."


class TestDMAgentEffectConversion:
    def test_resolution_to_effects(self, dm_agent):
        resolution = DMResolution(
            resolved_actions=[
                {
                    "character_id": "hero",
                    "intent": "Fight the fire",
                    "success_level": "success",
                    "effects": [
                        {
                            "target_type": "location",
                            "target_id": "marketplace",
                            "changes": {"environment": {"conditions": ["smoky"]}},
                            "description": "Hero douses the flames.",
                        }
                    ],
                    "description": "Hero successfully fights the fire.",
                }
            ],
            narrative="The fire is contained.",
            world_notes="",
        )
        effects = dm_agent.resolution_to_effects(resolution)
        assert len(effects) == 1
        assert effects[0].target_type == "location"
        assert effects[0].target_id == "marketplace"
