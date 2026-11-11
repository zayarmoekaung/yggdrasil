"""DM Agent — LLM-powered pool resolution via LangGraph."""

import json
import re
from pathlib import Path
from typing import Any

from aetherdm.baresexp_codec import build_dm_document, build_narrate_document, build_dm_prompt, encode_pool
from aetherdm.config import settings
from aetherdm.llm.provider import LLMProvider
from aetherdm.models import ActionPool, Character, DMResolution, Effect, LocationNode
from aetherdm.simulation.reaction import calculate_reaction_score


# ── Effect change sanitization ──

def _sanitize_resources(value: Any) -> dict[str, int]:
    """Coerce resources to dict[str, int].

    The LLM may send:
    - Correct: {"water": 10, "food": 5}
    - Wrong: [{"name": "smoke", "value": 6}]
    - Wrong: {"smoke": "partial"}
    """
    if isinstance(value, dict):
        return {k: _safe_int(v) for k, v in value.items()}
    if isinstance(value, list):
        result = {}
        for item in value:
            if isinstance(item, dict):
                name = item.get("name", item.get("resource", "unknown"))
                val = item.get("value", item.get("amount", 0))
                result[str(name)] = _safe_int(val)
            elif isinstance(item, (list, tuple)) and len(item) >= 2:
                result[str(item[0])] = _safe_int(item[1])
            else:
                result[str(item)] = 0
        return result
    return {}


def _safe_int(value: Any) -> int:
    """Try to coerce a value to int, returning 0 if impossible."""
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            try:
                return int(float(value))
            except ValueError:
                return 0
    return 0


def _sanitize_changes(changes: dict[str, Any]) -> dict[str, Any]:
    """Recursively coerce effect changes to match expected Pydantic field shapes.

    The LLM sees model_dump() output and may not know nested type schemas.
    This function normalizes common typed fields so that Character/Location
    reconstruction doesn't fail with ValidationError.
    """
    return _sanitize_dict(changes)


def _sanitize_dict(data: dict[str, Any]) -> dict[str, Any]:
    """Walk a dict and coerce known typed fields to their expected shapes."""
    result = dict(data)

    # Handle known character fields
    if "memory" in result:
        result["memory"] = _sanitize_memory(result["memory"])
    if "inventory" in result:
        result["inventory"] = _sanitize_list_of_objects(
            result["inventory"], required_keys={"id", "name"}, defaults={"description": "", "quantity": 1}
        )
    if "stats" in result and isinstance(result["stats"], dict):
        result["stats"] = {k: _safe_int(v) for k, v in result["stats"].items()}
    if "relationships" in result and isinstance(result["relationships"], dict):
        result["relationships"] = {k: _safe_int(v) for k, v in result["relationships"].items()}

    # Handle known location/environment fields
    if "environment" in result and isinstance(result["environment"], dict):
        env = result["environment"]
        if "objects" in env:
            env["objects"] = _sanitize_list_of_objects(
                env["objects"], required_keys={"id", "name"}, defaults={"description": "", "quantity": 1}
            )
        if "resources" in env:
            env["resources"] = _sanitize_resources(env["resources"])
        result["environment"] = env
    if "connections" in result:
        result["connections"] = _sanitize_connections_list(result["connections"])
    if "pending_effects" in result:
        result["pending_effects"] = _sanitize_list_of_objects(
            result["pending_effects"], required_keys={"target_type", "target_id"}, defaults={"changes": {}, "description": ""}
        )

    # Recurse into nested dicts that aren't handled above
    for key, value in result.items():
        if isinstance(value, dict) and key not in ("environment", "stats", "relationships"):
            result[key] = _sanitize_dict(value)

    return result


def _sanitize_memory(value: Any) -> list[dict[str, Any]]:
    """Normalize memory entries: strings → {round: 0, text: str}, dicts → fill defaults."""
    if not isinstance(value, list):
        return [{"round": 0, "text": str(value)}] if value else []

    entries = []
    for item in value:
        if isinstance(item, str):
            entries.append({"round": 0, "text": item})
        elif isinstance(item, dict):
            entry = {"round": int(item.get("round", 0)), "text": str(item.get("text", ""))}
            entries.append(entry)
        else:
            entries.append({"round": 0, "text": str(item)})
    return entries


def _sanitize_list_of_objects(items: Any, required_keys: set[str], defaults: dict[str, Any]) -> list[dict[str, Any]]:
    """Coerce a list of items into proper dict objects.

    - Strings become {id: slugified(name), name: str, ...defaults}
    - Dicts missing required keys get defaults filled in
    """
    if not isinstance(items, list):
        return []

    result = []
    for item in items:
        if isinstance(item, str):
            obj = dict(defaults)
            obj["id"] = _slugify(item)
            obj["name"] = item
            result.append(obj)
        elif isinstance(item, dict):
            obj = dict(defaults)
            obj.update(item)
            # Ensure required keys exist
            for key in required_keys:
                if key not in obj:
                    if key == "id":
                        obj["id"] = _slugify(obj.get("name", "unknown"))
                    elif key == "name":
                        obj["name"] = obj.get("id", "unknown")
                    elif key == "target_type":
                        obj["target_type"] = "character"
                    elif key == "target_id":
                        obj["target_id"] = ""
            result.append(obj)
        else:
            result.append({**defaults, "id": _slugify(str(item)), "name": str(item)})
    return result


def _sanitize_connection_list(items: Any) -> list[dict[str, Any]]:
    """Coerce connections to proper shape."""
    if not isinstance(items, list):
        return []

    defaults = {"type": "path", "travel_time": 1, "propagation_modifier": 1.0}
    result = []
    for item in items:
        if isinstance(item, str):
            result.append({**defaults, "target_id": _slugify(item)})
        elif isinstance(item, dict):
            obj = dict(defaults)
            obj.update(item)
            if "target_id" not in obj:
                obj["target_id"] = _slugify(obj.get("name", "unknown"))
            if "type" not in obj:
                obj["type"] = "path"
            result.append(obj)
        else:
            result.append({**defaults, "target_id": str(item)})
    return result


def _slugify(text: str) -> str:
    """Create a simple slug from text for use as IDs."""
    return re.sub(r'[^a-z0-9_]+', '_', text.lower().strip())


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
        """Delegate to the baresexp codec for the full DM prompt (legacy)."""
        return build_dm_prompt(pool, location, characters, mode=mode)

    def format_prompt(self, context: dict[str, str]) -> str:
        """Fill in the prompt template with context."""
        return self._prompt_template.format(**context)

    # ── Parsing ──

    def parse_llm_response(self, text: str) -> DMResolution:
        """Parse the LLM's JSON response into a DMResolution object.

        Handles multiple formats:
        1. Strict JSON object with resolved_actions, narrative, world_notes
        2. Flat array of [seq_num, {action_obj}, seq_num, {action_obj}, ...]
        3. Alternative field names (action_id→intent, target/target_id, etc.)
        """
        cleaned = text.strip()
        if cleaned.startswith("```"):
            lines = cleaned.split("\n")
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            cleaned = "\n".join(lines)

        data = json.loads(cleaned)

        # Handle flat array format: [seq_num, {action}, seq_num, {action}, ...]
        if isinstance(data, list):
            resolved_actions = []
            narrative_parts = []
            i = 0
            while i < len(data):
                if isinstance(data[i], (int, float)):
                    i += 1
                    continue
                obj = data[i]
                if isinstance(obj, dict):
                    normalized = self._normalize_action(obj)
                    resolved_actions.append(normalized)
                    if obj.get("narrative"):
                        narrative_parts.append(obj["narrative"])
                i += 1

            narrative = " ".join(narrative_parts) if narrative_parts else ""
            return DMResolution(
                resolved_actions=resolved_actions,
                narrative=narrative,
                world_notes="",
            )

        # Handle standard object format
        resolved_actions = []
        for ra in data.get("resolved_actions", []):
            normalized = self._normalize_action(ra)
            resolved_actions.append(normalized)

        return DMResolution(
            resolved_actions=resolved_actions,
            narrative=data.get("narrative", ""),
            world_notes=data.get("world_notes", data.get("notes", "")),
        )

    def _parse_baresexp_response(self, text: str) -> DMResolution:
        """Parse a BareSexp-formatted response into DMResolution.

        Expected format:
        (resolution
          (resolved-actions
            (action char_id intent success_level effects description)
            ...)
          (narrative "text")
          (world-notes "text")
        )

        Falls back to JSON parsing if baresexp parse fails.
        """
        from aetherdm.baresexp_codec import parse_baresexp

        cleaned = text.strip()
        if cleaned.startswith("```"):
            lines = cleaned.split("\n")
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            cleaned = "\n".join(lines)

        try:
            parsed = parse_baresexp(cleaned)
        except Exception:
            # Fall back to JSON parsing
            return self.parse_llm_response(text)

        # Extract resolution from parsed structure
        resolved_actions = []
        narrative = ""
        world_notes = ""

        def _extract_steps(obj, depth=0):
            nonlocal narrative, world_notes
            if not hasattr(obj, "steps"):
                return
            for step in obj.steps:
                if step.name == "resolved-actions":
                    for action_item in getattr(step, "items", []):
                        resolved_actions.append(self._normalize_baresexp_action(action_item))
                elif step.name == "narrative":
                    narrative = getattr(step, "description", "") or getattr(step, "content", "")
                elif step.name == "world-notes":
                    world_notes = getattr(step, "description", "") or getattr(step, "content", "")

        _extract_steps(parsed)

        # If no resolved_actions found, try top-level
        if not resolved_actions and hasattr(parsed, "name") and parsed.name == "resolution":
            # Try to find resolved-actions as a direct child
            for step in getattr(parsed, "steps", []):
                if step.name == "resolved-actions":
                    for item in getattr(step, "items", []):
                        resolved_actions.append(self._normalize_baresexp_action(item))
                elif step.name == "narrative":
                    narrative = getattr(step, "description", "")
                elif step.name == "world-notes":
                    world_notes = getattr(step, "description", "")

        return DMResolution(
            resolved_actions=resolved_actions,
            narrative=narrative,
            world_notes=world_notes,
        )

    def _normalize_baresexp_action(self, action_item) -> dict:
        """Normalize a baresexp action item to internal schema.

        BareSexp actions are tuples or objects depending on how the LLM formats them.
        """
        # If it's a dict (LLM might still use dict-like structure in baresexp)
        if isinstance(action_item, dict):
            return self._normalize_action(action_item)

        # If it's a tuple/list: (action char_id intent success_level effects description)
        if isinstance(action_item, (list, tuple)) and len(action_item) >= 3:
            # Skip the "action" keyword if present
            items = list(action_item)
            if items and items[0] == "action":
                items = items[1:]

            return {
                "character_id": str(items[0]) if len(items) > 0 else "",
                "intent": str(items[1]) if len(items) > 1 else "",
                "success_level": str(items[2]) if len(items) > 2 else "success",
                "effects": items[3] if len(items) > 3 and isinstance(items[3], list) else [],
                "description": str(items[4]) if len(items) > 4 else "",
            }

        # Fallback: try to normalize as dict
        return self._normalize_action({} if not isinstance(action_item, dict) else action_item)

    def _normalize_action(self, ra: dict) -> dict:
        """Normalize an LLM action object to the internal schema."""
        normalized = {
            "character_id": ra.get("character_id", ra.get("actor", ra.get("characte_id", ""))),
            "intent": ra.get("intent", ra.get("action", ra.get("description", ""))),
            "success_level": ra.get("success_level", ra.get("outcome", "success")),
            "effects": [],
            "description": ra.get("description", ra.get("narrative", "")),
        }

        for eff in ra.get("effects", []):
            norm_eff = {
                "target_type": eff.get("target_type", eff.get("type", "character")),
                "target_id": eff.get("target_id", eff.get("target", "")),
                "changes": eff.get("changes", {"narrative": eff.get("change", eff.get("description", ""))}),
                "description": eff.get("description", eff.get("change", eff.get("narrative", ""))),
            }
            normalized["effects"].append(norm_eff)

        return normalized

    def resolution_to_effects(self, resolution: DMResolution) -> list[Effect]:
        """Convert a DMResolution into a list of Effect objects, sanitizing LLM output.

        The LLM may produce effect changes with incorrect shapes for Pydantic-typed
        fields (e.g., memory as list[str] instead of list[{round, text}]). This method
        normalizes all changes before constructing Effect objects.
        """
        effects = []
        for resolved in resolution.resolved_actions:
            for effect_data in resolved.effects:
                effect_data = dict(effect_data)  # don't mutate original
                effect_data["changes"] = _sanitize_changes(effect_data.get("changes", {}))
                effects.append(Effect(**effect_data))
        return effects

    # ── Async resolution (legacy) ──

    async def resolve_pool(
        self,
        pool: ActionPool,
        location: LocationNode,
        characters: list[Character],
    ) -> DMResolution:
        """Resolve an action pool using the LLM (async).

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
            return self._fallback_resolve(pool, characters)

    # ── Dual-model resolution + narration ──

    def resolve_pool_sync(
        self,
        pool: ActionPool,
        location: LocationNode,
        characters: list[Character],
        output_format: str = "json",
    ) -> DMResolution:
        """Resolve an action pool using the LLM (sync, dual-model).

        Uses the resolution model (cheap/fast) for structured output.
        The narrative field in the returned DMResolution is minimal —
        use narrate_sync() for verbose prose.

        Args:
            output_format: "json" (default) or "baresexp" — controls output format instruction.
        """
        if self.llm is None:
            if self.debug:
                print("\n[DM DEBUG] LLM not configured — using fallback\n")
            return self._fallback_resolve(pool, characters)

        # Build BareSexpDocument with compile_parts()
        prompt = build_dm_document(
            pool, location, characters, output_format=output_format
        )

        system_msg = prompt.system_msg
        user_msg = prompt.user_msg
        token_count = prompt.token_count

        messages = [
            {"role": "system", "content": system_msg},
            {"role": "user", "content": user_msg},
        ]

        if self.debug:
            print(f"\n{'='*60}")
            print(f"[DM] Resolving: {pool.location_id} round={pool.round} | Tokens: {token_count}")
            print(f"[DM] Actions: {'; '.join(a.intent[:60] for a in pool.actions)}")
            print(f"[DM] Output format: {output_format}")
            print(f"[DM] System prompt ({len(system_msg)} chars):")
            print(system_msg[:600])
            if len(system_msg) > 600:
                print(f"  ... ({len(system_msg) - 600} more chars)")
            print(f"[DM] User message ({len(user_msg)} chars):")
            print(user_msg[:600])
            if len(user_msg) > 600:
                print(f"  ... ({len(user_msg) - 600} more chars)")
            print(f"{'='*60}")

        # Use resolution model (cheap/fast)
        resolution_model = settings.resolution_model

        try:
            if self.debug:
                print(f"[DM] Calling LLM (model={resolution_model})... ", end="", flush=True)
            response_text = self.llm.chat_sync(
                messages,
                temperature=0.7,
                max_tokens=2048,
                response_format={"type": "json_object"} if output_format == "json" else None,
                model=resolution_model,
            )
            if self.debug:
                print(f"done ({len(response_text)} chars)")
                print(f"[DM] Raw response:\n{response_text[:800]}")
                if len(response_text) > 800:
                    print(f"... ({len(response_text) - 800} more chars)")

            # Parse based on output format
            if output_format == "baresexp":
                resolution = self._parse_baresexp_response(response_text)
            else:
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

    def narrate_sync(
        self,
        pool: ActionPool,
        location: LocationNode,
        resolution: DMResolution,
    ) -> str:
        """Generate verbose narrative prose for a resolution.

        Uses the narrative model (expensive/verbose) for rich prose.
        Called only for PC locations or transition narration.

        The narrative expands from the resolution model's output — it anchors to
        the resolution's narrative and action descriptions rather than inventing
        new events, preventing drift between the two models.

        Uses BareSexpDocument for uniform prompt structure (same as resolve_pool_sync).

        Returns:
            Narrative string.
        """
        if self.llm is None:
            return self._fallback_narrative(pool, resolution)

        # Build action descriptions from resolved actions
        action_details = []
        for ra in resolution.resolved_actions:
            effect_list = "; ".join(
                eff.get("description", "") for eff in ra.effects
            )
            action_details.append(
                f"{ra.character_id} ({ra.success_level}): {ra.description}"
                + (f" | Effects: {effect_list}" if effect_list else "")
            )

        # Anchor to the resolution model's narrative
        resolution_narrative = resolution.narrative or "(no narrative provided)"

        # Build BareSexpDocument for narration (uniform with resolution)
        narrate_prompt = build_narrate_document(
            location, pool, resolution_narrative, action_details
        )

        messages = [
            {"role": "system", "content": narrate_prompt.system_msg},
            {"role": "user", "content": narrate_prompt.user_msg},
        ]

        narrative_model = settings.narrative_model

        try:
            if self.debug:
                print(f"[DM NARRATE] Calling LLM (model={narrative_model}) | Tokens: {narrate_prompt.token_count}... ", end="", flush=True)
            response = self.llm.chat_sync(
                messages,
                temperature=0.8,
                max_tokens=1024,
                model=narrative_model,
            )
            if self.debug:
                print(f"done ({len(response)} chars)")
            return response.strip()
        except Exception as e:
            if self.debug:
                print(f"[DM NARRATE] Failed ({type(e).__name__}: {e}) — fallback")
            return self._fallback_narrative(pool, resolution)

    def _fallback_narrative(self, pool: ActionPool, resolution: DMResolution) -> str:
        """Generate a basic narrative when LLM is unavailable."""
        parts = []
        for ra in resolution.resolved_actions:
            parts.append(ra.description)
        return " ".join(parts) if parts else f"Nothing notable happened at {pool.location_id}."

    # ── Rule-based fallback ──

    def _fallback_resolve(
        self, pool: ActionPool, characters: list[Character]
    ) -> DMResolution:
        """Rule-based fallback: resolve actions with basic contextual logic."""
        from aetherdm.simulation.eligibility import filter_eligible

        eligible = filter_eligible(characters)
        eligible_ids = {ch.id for ch in eligible}
        char_map = {ch.id: ch for ch in characters}

        resolved = []
        narrative_parts: list[str] = []

        for action in pool.actions:
            if action.character_id not in eligible_ids:
                narrative_parts.append(
                    f"{action.character_id} was unable to act ({action.intent})."
                )
                continue

            ch = char_map.get(action.character_id)
            intent = action.intent.lower()

            effects_list: list[dict] = []

            if any(w in intent for w in ("fire", "bucket", "extinguish", "water", "flame", "burn")):
                effects_list.append({
                    "target_type": "location",
                    "target_id": pool.location_id,
                    "changes": {"environment": {"flags": {"fire_intensity": -2}}},
                    "description": f"{action.character_id} fights the fire: {action.intent}",
                })

            if any(w in intent for w in ("heal", "bandage", "treat", "medicine")):
                effects_list.append({
                    "target_type": "character",
                    "target_id": action.character_id,
                    "changes": {"conditions": ["healing"]},
                    "description": f"{action.character_id} tends to wounds: {action.intent}",
                })

            if any(w in intent for w in ("move", "go", "walk", "run", "flee", "head to")):
                effects_list.append({
                    "target_type": "character",
                    "target_id": action.character_id,
                    "changes": {"conditions": ["moved"]},
                    "description": f"{action.character_id} moves: {action.intent}",
                })

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
