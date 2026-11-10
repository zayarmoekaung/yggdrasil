"""DM Agent — LLM-powered pool resolution via LangGraph."""

import json
import sys
from pathlib import Path
from typing import Any

from aetherdm.baresexp_codec import build_dm_prompt, encode_pool
from aetherdm.llm.provider import LLMProvider
from aetherdm.models import ActionPool, Character, DMResolution, Effect, LocationNode
from aetherdm.simulation.reaction import calculate_reaction_score


class DMAgent:
    """Dungeon Master agent powered by an LLM.

    Receives the action pool, location state, and character context,
    then uses the LLM to resolve actions with full contextual understanding.
    Falls back to rule-based resolution if the LLM is unavailable.
    """

    def __init__(self, llm: LLMProvider | None = None, debug: bool = False):
        self.llm = llm
        self._prompt_template = self._load_prompt()
        self.debug = debug

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

    def build_context_baresexp(
        self,
        pool: ActionPool,
        location: LocationNode,
        characters: list[Character],
        mode: str = "minimal",
    ) -> tuple[str, int]:
        """Delegate to the baresexp codec for the full DM prompt."""
        return build_dm_prompt(pool, location, characters, mode=mode)

    def format_prompt(self, context: dict[str, str]) -> str:
        """Fill in the prompt template with context."""
        return self._prompt_template.format(**context)

    def parse_llm_response(self, text: str) -> DMResolution:
        """Parse the LLM's JSON response into a DMResolution object.

        Handles both strict JSON mode and the LLM's tendency to use
        alternative field names (action_id→intent, target/target_id, etc).
        """
        # Try to extract JSON from markdown code blocks
        cleaned = text.strip()
        if cleaned.startswith("```"):
            lines = cleaned.split("\n")
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            cleaned = "\n".join(lines)

        data = json.loads(cleaned)

        # Normalize LLM's alternative field names to match DMResolution schema
        resolved_actions = []
        for ra in data.get("resolved_actions", []):
            normalized = {
                "character_id": ra.get("character_id", ra.get("actor", "")),
                "intent": ra.get("intent", ra.get("action", ra.get("description", ""))),
                "success_level": ra.get("success_level", ra.get("outcome", "success")),
                "effects": [],
                "description": ra.get("description", ra.get("narrative", "")),
            }

            # Normalize effects: LLM may use {target, type, change} instead of {target_type, target_id, changes, description}
            for eff in ra.get("effects", []):
                norm_eff = {
                    "target_type": eff.get("target_type", eff.get("type", "character")),
                    "target_id": eff.get("target_id", eff.get("target", "")),
                    "changes": eff.get("changes", {"narrative": eff.get("change", eff.get("description", ""))}),
                    "description": eff.get("description", eff.get("change", eff.get("narrative", ""))),
                }
                normalized["effects"].append(norm_eff)

            resolved_actions.append(normalized)

        return DMResolution(
            resolved_actions=resolved_actions,
            narrative=data.get("narrative", ""),
            world_notes=data.get("world_notes", data.get("notes", "")),
        )

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
        use_baresexp: bool = True,
    ) -> DMResolution:
        """Synchronous version of resolve_pool.

        Args:
            use_baresexp: If True, uses compact baresexp for context (fewer tokens).
                          If False, uses the full verbose text context.
        """
        if self.llm is None:
            if self.debug:
                print("\n[DM DEBUG] LLM not configured — using fallback\n")
            return self._fallback_resolve(pool, characters)

        if use_baresexp:
            context_str, token_count = self.build_context_baresexp(pool, location, characters)
            system_msg = (
                f"You are a Dungeon Master resolving actions in a text-based RPG. "
                f"The context below is in BareSexp format ({token_count} tokens). "
                f"Read it carefully, resolve the action pool, and return ONLY valid JSON "
                f"with resolved_actions, narrative, and world_notes."
            )
            user_msg = context_str
        else:
            context = self.build_context(pool, location, characters)
            prompt = self.format_prompt(context)
            system_msg = "You are a Dungeon Master resolving actions in a text-based RPG."
            user_msg = prompt

        messages = [
            {"role": "system", "content": system_msg},
            {"role": "user", "content": user_msg},
        ]

        if self.debug:
            print(f"\n{'='*60}")
            print(f"[DM] Resolving: {pool.location_id} round={pool.round} | Tokens: {token_count if use_baresexp else 'verbose'}")
            print(f"[DM] Actions: {'; '.join(a.intent[:60] for a in pool.actions)}")
            # Show the structured context+task header (first ~400 chars)
            header_end = user_msg.find("\n\n;; Raw encoded state")
            if header_end > 0:
                print(f"[DM] Context+Task prompt:")
                print(user_msg[:header_end])
                print(f"[DM] Raw encoded state ({len(user_msg) - header_end} chars):")
                print(user_msg[header_end:header_end+500])
                if len(user_msg) > header_end + 500:
                    print(f"  ... ({len(user_msg) - header_end - 500} more chars of raw state)")
            else:
                print(f"[DM] Prompt ({len(user_msg)} chars):")
                print(user_msg[:800])
            print(f"[DM] FULL prompt sent to LLM: {len(user_msg)} chars, {token_count} tokens")
            print(f"{'='*60}")

        try:
            if self.debug:
                print("[DM] Calling LLM... ", end="", flush=True)
            response_text = self.llm.chat_sync(
                messages,
                temperature=0.7,
                max_tokens=2048,
                response_format={"type": "json_object"},
            )
            if self.debug:
                print(f"done ({len(response_text)} chars)")
                print(f"[DM] Raw response:\n{response_text[:800]}")
                if len(response_text) > 800:
                    print(f"... ({len(response_text) - 800} more chars)")
            resolution = self.parse_llm_response(response_text)
            if self.debug:
                print(f"[DM] Parsed: {len(resolution.resolved_actions)} actions")
                for ra in resolution.resolved_actions:
                    print(f"  {ra.character_id}: {ra.success_level} — {ra.description[:80]}")
                    for eff in ra.effects:
                        print(f"    → {eff['target_type']}:{eff['target_id']} — {eff.get('description', '')[:60]}")
                print(f"[DM] Narrative: {resolution.narrative[:150]}")
                print(f"{'='*60}\n")
            return resolution
        except Exception as e:
            if self.debug:
                print(f"[DM] LLM failed ({type(e).__name__}: {e}) — fallback")
            return self._fallback_resolve(pool, characters)

    def _fallback_resolve(
        self, pool: ActionPool, characters: list[Character]
    ) -> DMResolution:
        """Rule-based fallback: resolve actions with basic contextual logic.

        Produces:
        - Character-level effects (mark actions as taken)
        - Location-level effects based on action intent keywords
        - A readable narrative describing what happened
        """
        from aetherdm.simulation.eligibility import filter_eligible

        eligible = filter_eligible(characters)
        eligible_ids = {ch.id for ch in eligible}

        # Build character lookup for intent-based effects
        char_map = {ch.id: ch for ch in characters}

        resolved = []
        location_effects: list[dict] = []
        narrative_parts: list[str] = []

        for action in pool.actions:
            if action.character_id not in eligible_ids:
                narrative_parts.append(
                    f"{action.character_id} was unable to act ({action.intent})."
                )
                continue

            ch = char_map.get(action.character_id)
            intent = action.intent.lower()

            # Basic intent recognition for location effects
            effects_list: list[dict] = []

            # Fire-fighting intent reduces fire intensity
            if any(w in intent for w in ("fire", "bucket", "extinguish", "water", "flame", "burn")):
                effects_list.append({
                    "target_type": "location",
                    "target_id": pool.location_id,
                    "changes": {"environment": {"flags": {"fire_intensity": -2}}},
                    "description": f"{action.character_id} fights the fire: {action.intent}",
                })

            # Healing intent
            if any(w in intent for w in ("heal", "bandage", "treat", "medicine")):
                effects_list.append({
                    "target_type": "character",
                    "target_id": action.character_id,
                    "changes": {"conditions": ["healing"]},
                    "description": f"{action.character_id} tends to wounds: {action.intent}",
                })

            # Movement intent
            if any(w in intent for w in ("move", "go", "walk", "run", "flee", "head to")):
                effects_list.append({
                    "target_type": "character",
                    "target_id": action.character_id,
                    "changes": {"conditions": ["moved"]},
                    "description": f"{action.character_id} moves: {action.intent}",
                })

            # Always mark character as having acted
            effects_list.append({
                "target_type": "character",
                "target_id": action.character_id,
                "changes": {"conditions": ["acted"]},
                "description": f"{action.character_id} acted: {action.intent}",
            })

            resolved.append({
                "character_id": action.character_id,
                "intent": action.intent,
                "success_level": "success",
                "effects": effects_list,
                "description": f"{ch.name if ch else action.character_id} {action.intent.lower()}.",
            })
            narrative_parts.append(f"{ch.name if ch else action.character_id} {action.intent.lower()}." if ch else f"{action.character_id} acts: {action.intent}.")

        narrative = " ".join(narrative_parts) if narrative_parts else f"[Round {pool.round}] Nothing happened at {pool.location_id}."

        return DMResolution(
            resolved_actions=resolved,
            narrative=narrative,
            world_notes="",
        )
