"""DM Agent — LLM-powered pool resolution via LangGraph."""

import json
from pathlib import Path
from typing import Any

from aetherdm.llm.provider import LLMProvider
from aetherdm.models import ActionPool, Character, DMResolution, Effect, LocationNode
from aetherdm.simulation.reaction import calculate_reaction_score


class DMAgent:
    """Dungeon Master agent powered by an LLM.

    Receives the action pool, location state, and character context,
    then uses the LLM to resolve actions with full contextual understanding.
    Falls back to rule-based resolution if the LLM is unavailable.
    """

    def __init__(self, llm: LLMProvider | None = None):
        self.llm = llm
        self._prompt_template = self._load_prompt()

    def _load_prompt(self) -> str:
        prompt_path = Path(__file__).parent / "prompts" / "dm_v1.txt"
        return prompt_path.read_text(encoding="utf-8")

    def build_context(
        self,
        pool: ActionPool,
        location: LocationNode,
        characters: list[Character],
    ) -> dict[str, str]:
        """Build the context dict for the DM prompt."""
        char_lines = []
        for ch in characters:
            score = calculate_reaction_score(ch)
            char_lines.append(
                f"- **{ch.id}** ({ch.name}, type={ch.type}, quickness={ch.quickness}, "
                f"reaction_score={score:.1f})\n"
                f"  Conditions: {', '.join(ch.conditions) if ch.conditions else 'none'}\n"
                f"  Personality: {ch.personality}\n"
                f"  Goals: {', '.join(ch.goals) if ch.goals else 'none'}\n"
                f"  Secrets: {', '.join(ch.secrets) if ch.secrets else 'none'}"
            )

        action_lines = []
        for i, action in enumerate(pool.actions, 1):
            line = f"{i}. **{action.character_id}**: {action.intent}"
            if action.focused:
                line += " (focused reaction)"
            action_lines.append(line)

        return {
            "location_name": location.name,
            "location_description": location.description,
            "environment_conditions": ", ".join(location.environment.conditions) if location.environment.conditions else "none",
            "round": str(pool.round),
            "character_context": "\n\n".join(char_lines) if char_lines else "(no characters)",
            "action_context": "\n".join(action_lines) if action_lines else "(no actions declared)",
        }

    def format_prompt(self, context: dict[str, str]) -> str:
        """Fill in the prompt template with context."""
        return self._prompt_template.format(**context)

    def parse_llm_response(self, text: str) -> DMResolution:
        """Parse the LLM's JSON response into a DMResolution object."""
        # Try to extract JSON from markdown code blocks
        cleaned = text.strip()
        if cleaned.startswith("```"):
            lines = cleaned.split("\n")
            # Remove opening backtick line (with or without language tag)
            if lines[0].startswith("```"):
                lines = lines[1:]
            # Remove closing backtick line
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            cleaned = "\n".join(lines)

        data = json.loads(cleaned)
        return DMResolution(**data)

    def resolution_to_effects(self, resolution: DMResolution) -> list[Effect]:
        """Convert a DMResolution into a list of Effect objects."""
        effects = []
        for resolved in resolution.resolved_actions:
            for effect_data in resolved.effects:
                effects.append(Effect(**effect_data))
        return effects

    async def resolve_pool(
        self,
        pool: ActionPool,
        location: LocationNode,
        characters: list[Character],
    ) -> DMResolution:
        """Resolve an action pool using the LLM.

        Falls back to rule-based resolution if LLM is unavailable.
        """
        if self.llm is None:
            return self._fallback_resolve(pool, characters)

        context = self.build_context(pool, location, characters)
        prompt = self.format_prompt(context)

        messages = [
            {"role": "system", "content": "You are a Dungeon Master resolving actions in a text-based RPG."},
            {"role": "user", "content": prompt},
        ]

        try:
            response_text = await self.llm.chat(
                messages,
                temperature=0.7,
                max_tokens=2048,
                response_format={"type": "json_object"},
            )
            return self.parse_llm_response(response_text)
        except Exception:
            # Fallback to rule-based if LLM call fails
            return self._fallback_resolve(pool, characters)

    def resolve_pool_sync(
        self,
        pool: ActionPool,
        location: LocationNode,
        characters: list[Character],
    ) -> DMResolution:
        """Synchronous version of resolve_pool."""
        if self.llm is None:
            return self._fallback_resolve(pool, characters)

        context = self.build_context(pool, location, characters)
        prompt = self.format_prompt(context)

        messages = [
            {"role": "system", "content": "You are a Dungeon Master resolving actions in a text-based RPG."},
            {"role": "user", "content": prompt},
        ]

        try:
            response_text = self.llm.chat_sync(
                messages,
                temperature=0.7,
                max_tokens=2048,
                response_format={"type": "json_object"},
            )
            return self.parse_llm_response(response_text)
        except Exception:
            return self._fallback_resolve(pool, characters)

    def _fallback_resolve(
        self, pool: ActionPool, characters: list[Character]
    ) -> DMResolution:
        """Rule-based fallback: all eligible characters' actions succeed with 'success' level."""
        from aetherdm.simulation.eligibility import filter_eligible

        eligible = filter_eligible(characters)
        eligible_ids = {ch.id for ch in eligible}
        resolved = []
        for action in pool.actions:
            if action.character_id not in eligible_ids:
                continue
            resolved.append(
                {
                    "character_id": action.character_id,
                    "intent": action.intent,
                    "success_level": "success",
                    "effects": [
                        {
                            "target_type": "character",
                            "target_id": action.character_id,
                            "changes": {"conditions": ["acted"]},
                            "description": f"{action.character_id} acted: {action.intent}",
                        }
                    ],
                    "description": f"{action.character_id} successfully: {action.intent}",
                }
            )
        return DMResolution(
            resolved_actions=resolved,
            narrative=f"[Round {pool.round}] Actions resolved at {pool.location_id}.",
            world_notes="",
        )
