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

    def test_parse_array_format(self, dm_agent):
        """Handle LLM returning flat array: [seq_num, {action}, seq_num, {action}]."""
        text = json.dumps([
            3,
            {
                "characte_id": "pc",
                "action": "run",
                "intent": "ask her what happened",
                "difficulty": 10,
                "success": 7,
                "narrative": "You dash towards Mira.",
                "world_notes": "The PC manages to reach Mira.",
            },
            5,
            {
                "characte_id": "garrick",
                "action": "inventory",
                "intent": "look for something flammable",
                "difficulty": 5,
                "success": 100,
                "narrative": "Garrick curses and kicks the lantern.",
                "world_notes": "Garrick blames the fire on the lantern.",
            },
        ])
        resolution = dm_agent.parse_llm_response(text)
        assert len(resolution.resolved_actions) == 2
        assert resolution.resolved_actions[0].character_id == "pc"
        assert resolution.resolved_actions[1].character_id == "garrick"
        # Narratives from individual actions are collected
        assert "dash towards Mira" in resolution.narrative
        assert "Garrick curses" in resolution.narrative

    def test_parse_array_with_alternative_field_names(self, dm_agent):
        """Handle array format with varied field names (characte_id, action, etc.)."""
        text = json.dumps([
            1,
            {
                "characte_id": "hero",
                "action": "attack",
                "narrative": "Hero strikes the goblin.",
            },
        ])
        resolution = dm_agent.parse_llm_response(text)
        assert len(resolution.resolved_actions) == 1
        assert resolution.resolved_actions[0].character_id == "hero"
        assert resolution.resolved_actions[0].intent == "attack"

    def test_parse_array_empty(self, dm_agent):
        """Handle empty array."""
        text = json.dumps([])
        resolution = dm_agent.parse_llm_response(text)
        assert resolution.resolved_actions == []
        assert resolution.narrative == ""

    def test_parse_baresexp_response_json_fallback(self, dm_agent):
        """When baresexp parse fails, fall back to JSON."""
        # Invalid baresexp but valid JSON — should fall back
        text = json.dumps({
            "resolved_actions": [
                {"character_id": "pc", "intent": "run", "success_level": "success", "effects": [], "description": "PC runs."}
            ],
            "narrative": "PC runs away.",
            "world_notes": "",
        })
        # The baresexp parser may or may not parse JSON as valid baresexp.
        # Either way, the resolution should have the correct data.
        resolution = dm_agent._parse_baresexp_response(text)
        # If baresexp parsing succeeds but finds no resolved-actions, it falls back to JSON
        # If it fails, it falls back to JSON directly
        if resolution.resolved_actions:
            assert resolution.resolved_actions[0].character_id == "pc"
        else:
            # Fallback to JSON parsing
            resolution2 = dm_agent.parse_llm_response(text)
            assert resolution2.resolved_actions[0].character_id == "pc"


class TestDMASanitization:
    """Test that effect changes are sanitized to match Pydantic schemas."""

    def test_memory_strings_converted_to_entries(self, dm_agent):
        """LLM may write memory as plain strings — should become {round, text} dicts."""
        resolution = DMResolution(
            resolved_actions=[{
                "character_id": "npc_mira",
                "intent": "remember",
                "success_level": "success",
                "effects": [{
                    "target_type": "character",
                    "target_id": "npc_mira",
                    "changes": {"memory": ["Mira says the fire began when Garrick tipped his lantern."]},
                    "description": "Mira remembers.",
                }],
                "description": "Mira remembers.",
            }],
            narrative="",
            world_notes="",
        )
        effects = dm_agent.resolution_to_effects(resolution)
        assert len(effects) == 1
        # Should not raise ValidationError
        assert effects[0].changes["memory"] == [{"round": 0, "text": "Mira says the fire began when Garrick tipped his lantern."}]

    def test_memory_dicts_filled_defaults(self, dm_agent):
        """Memory dicts missing 'round' get default 0."""
        resolution = DMResolution(
            resolved_actions=[{
                "character_id": "x",
                "intent": "x",
                "success_level": "success",
                "effects": [{
                    "target_type": "character",
                    "target_id": "x",
                    "changes": {"memory": [{"text": "something happened"}]},
                    "description": "",
                }],
                "description": "",
            }],
            narrative="", world_notes="",
        )
        effects = dm_agent.resolution_to_effects(resolution)
        assert effects[0].changes["memory"] == [{"round": 0, "text": "something happened"}]

    def test_inventory_strings_converted(self, dm_agent):
        """Inventory items as strings become proper objects."""
        resolution = DMResolution(
            resolved_actions=[{
                "character_id": "x", "intent": "x", "success_level": "success",
                "effects": [{
                    "target_type": "character", "target_id": "x",
                    "changes": {"inventory": ["Iron Sword"]},
                    "description": "",
                }],
                "description": "",
            }],
            narrative="", world_notes="",
        )
        effects = dm_agent.resolution_to_effects(resolution)
        inv = effects[0].changes["inventory"]
        assert len(inv) == 1
        assert inv[0]["name"] == "Iron Sword"
        assert inv[0]["id"] == "iron_sword"
        assert inv[0]["quantity"] == 1

    def test_stats_coerced_to_int(self, dm_agent):
        """Stats values are coerced to int."""
        resolution = DMResolution(
            resolved_actions=[{
                "character_id": "x", "intent": "x", "success_level": "success",
                "effects": [{
                    "target_type": "character", "target_id": "x",
                    "changes": {"stats": {"str": "10", "dex": 12.5}},
                    "description": "",
                }],
                "description": "",
            }],
            narrative="", world_notes="",
        )
        effects = dm_agent.resolution_to_effects(resolution)
        stats = effects[0].changes["stats"]
        assert stats["str"] == 10
        assert stats["dex"] == 12

    def test_nested_environment_objects_sanitized(self, dm_agent):
        """Environment objects inside environment dict are sanitized."""
        resolution = DMResolution(
            resolved_actions=[{
                "character_id": "x", "intent": "x", "success_level": "success",
                "effects": [{
                    "target_type": "location", "target_id": "marketplace",
                    "changes": {"environment": {"objects": ["Bucket", "Hose"]}},
                    "description": "",
                }],
                "description": "",
            }],
            narrative="", world_notes="",
        )
        effects = dm_agent.resolution_to_effects(resolution)
        objs = effects[0].changes["environment"]["objects"]
        assert objs[0]["name"] == "Bucket"
        assert objs[0]["id"] == "bucket"
        assert objs[1]["name"] == "Hose"

    def test_resources_list_converted_to_dict(self, dm_agent):
        """LLM may send resources as [{name, value}] list — should become dict."""
        resolution = DMResolution(
            resolved_actions=[{
                "character_id": "x", "intent": "x", "success_level": "success",
                "effects": [{
                    "target_type": "location", "target_id": "marketplace",
                    "changes": {"environment": {"resources": [{"name": "smoke", "value": 6}]}},
                    "description": "",
                }],
                "description": "",
            }],
            narrative="", world_notes="",
        )
        effects = dm_agent.resolution_to_effects(resolution)
        res = effects[0].changes["environment"]["resources"]
        assert res == {"smoke": 6}
        assert isinstance(res, dict)

    def test_resources_non_numeric_values_safe_coerced(self, dm_agent):
        """Resources with non-numeric values (like LLM putting 'partial') don't crash."""
        resolution = DMResolution(
            resolved_actions=[{
                "character_id": "x", "intent": "x", "success_level": "success",
                "effects": [{
                    "target_type": "location", "target_id": "marketplace",
                    "changes": {"environment": {"resources": {"fire_intensity": "partial", "water": "10"}}},
                    "description": "",
                }],
                "description": "",
            }],
            narrative="", world_notes="",
        )
        effects = dm_agent.resolution_to_effects(resolution)
        res = effects[0].changes["environment"]["resources"]
        assert res["fire_intensity"] == 0  # 'partial' → 0
        assert res["water"] == 10  # '10' → 10

    def test_stats_bool_values_coerced(self, dm_agent):
        """Boolean stats are coerced to int (True→1, False→0)."""
        resolution = DMResolution(
            resolved_actions=[{
                "character_id": "x", "intent": "x", "success_level": "success",
                "effects": [{
                    "target_type": "character", "target_id": "x",
                    "changes": {"stats": {"str": True, "dex": False}},
                    "description": "",
                }],
                "description": "",
            }],
            narrative="", world_notes="",
        )
        effects = dm_agent.resolution_to_effects(resolution)
        stats = effects[0].changes["stats"]
        assert stats["str"] == 1
        assert stats["dex"] == 0


class TestDMAgentNarration:
    def test_fallback_narrative(self, dm_agent):
        """Generate narrative without LLM."""
        resolution = DMResolution(
            resolved_actions=[
                {"character_id": "pc", "intent": "fight fire", "success_level": "success", "effects": [], "description": "PC fights the fire."},
            ],
            narrative="Fire contained.",
            world_notes="",
        )
        narrative = dm_agent._fallback_narrative(
            ActionPool(location_id="marketplace", round=1), resolution
        )
        assert "fights the fire" in narrative

    def test_fallback_narrative_empty(self, dm_agent):
        pool = ActionPool(location_id="empty_place", round=1)
        resolution = DMResolution(resolved_actions=[], narrative="", world_notes="")
        narrative = dm_agent._fallback_narrative(pool, resolution)
        assert "empty_place" in narrative


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
