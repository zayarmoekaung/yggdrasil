"""BareSexp serialization codec — converts Pydantic models to/from compact s-expressions."""

from typing import Any

from baresexp import BareSexpBuilder, BareSexpResult, builder, compile_baresexp, parse_baresexp

from aetherdm.models import (
    ActionPool,
    Character,
    Connection,
    Effect,
    Environment,
    Event,
    LocationNode,
)
from aetherdm.simulation.reaction import calculate_reaction_score


# ── Encoders ──


def encode_location(loc: LocationNode, mode: str = "minimal") -> BareSexpResult:
    """Encode a LocationNode to compact baresexp."""
    conn_parts = []
    for c in loc.connections:
        conn_parts.append(
            f"{c.target_id}:{c.type}:{c.travel_time}:{c.propagation_modifier}"
        )

    env_parts = []
    if loc.environment.conditions:
        env_parts.append(f"conditions={','.join(loc.environment.conditions)}")
    if loc.environment.objects:
        obj_names = [o.name for o in loc.environment.objects]
        env_parts.append(f"objects={','.join(obj_names)}")
    if loc.environment.resources:
        res_parts = [f"{k}={v}" for k, v in loc.environment.resources.items()]
        env_parts.append(f"resources={','.join(res_parts)}")
    if loc.environment.flags:
        flag_parts = [f"{k}={v}" for k, v in loc.environment.flags.items()]
        env_parts.append(f"flags={','.join(flag_parts)}")

    task = (
        BareSexpBuilder()
        .task(f"location:{loc.id}", description=loc.name)
        .step("meta", description=f"tags={','.join(loc.tags)}|round={loc.last_mutated_round}")
        .step("connections", description="|".join(conn_parts) if conn_parts else "none")
        .step("environment", description="|".join(env_parts) if env_parts else "empty")
        .step("occupants", description="|".join(loc.characters) if loc.characters else "empty")
        .build()
    )
    return compile_baresexp(task, mode=mode)


def encode_character(ch: Character, mode: str = "minimal") -> BareSexpResult:
    """Encode a Character to compact baresexp."""
    stats_parts = [f"{k}={v}" for k, v in ch.stats.items()]
    inv_names = [i.name for i in ch.inventory]

    task = (
        BareSexpBuilder()
        .task(f"character:{ch.id}", description=ch.name)
        .step(
            "meta",
            description=(
                f"type={ch.type}|loc={ch.location_id}|quickness={ch.quickness}"
                f"|stats={','.join(stats_parts) if stats_parts else 'none'}"
            ),
        )
        .step(
            "state",
            description=(
                f"conditions={','.join(ch.conditions) if ch.conditions else 'none'}"
                f"|inventory={','.join(inv_names) if inv_names else 'none'}"
                f"|last_action_round={ch.last_action_round}"
            ),
        )
        .step("agency", description=ch.personality[:120] if ch.personality else "none")
        .step("goals", description="|".join(ch.goals) if ch.goals else "none")
        .step("secrets", description="|".join(ch.secrets) if ch.secrets else "none")
        .step(
            "relations",
            description="|".join(f"{k}={v}" for k, v in ch.relationships.items())
            if ch.relationships
            else "none",
        )
        .build()
    )
    return compile_baresexp(task, mode=mode)


def encode_pool(pool: ActionPool, mode: str = "minimal") -> BareSexpResult:
    """Encode an ActionPool to compact baresexp."""
    action_parts = []
    for a in pool.actions:
        parts = [a.character_id, a.intent.replace("|", "/")]
        if a.focused:
            parts.append("focused")
        if a.reaction_to:
            parts.append(f"reacts_to={','.join(a.reaction_to)}")
        action_parts.append(":".join(parts))

    task = (
        BareSexpBuilder()
        .task(f"pool:{pool.location_id}", description=f"round={pool.round}")
        .step("status", description=pool.status)
        .step("actions", description="|".join(action_parts) if action_parts else "empty")
        .build()
    )
    return compile_baresexp(task, mode=mode)


def encode_effect(effect: Effect, mode: str = "minimal") -> BareSexpResult:
    """Encode a single Effect to compact baresexp."""
    changes_str = _flatten_dict(effect.changes)
    task = (
        BareSexpBuilder()
        .task("effect", description=f"{effect.target_type}:{effect.target_id}")
        .step("changes", description=changes_str)
        .step("desc", description=effect.description[:200] if effect.description else "")
        .build()
    )
    return compile_baresexp(task, mode=mode)


def encode_world_state(
    locations: list[LocationNode],
    characters: list[Character],
    round_num: int,
    mode: str = "minimal",
) -> BareSexpResult:
    """Encode entire world state as one compact baresexp.

    This is what gets sent to the DM as context — far fewer tokens than full JSON.
    """
    task = (
        BareSexpBuilder()
        .task("world", description=f"round={round_num}")
        .step(
            "locations",
            description="|".join(
                f"{loc.id}:{loc.name}:{','.join(loc.environment.conditions) if loc.environment.conditions else 'clean'}"
                for loc in locations
            ),
        )
        .step(
            "characters",
            description="|".join(
                f"{ch.id}@{ch.location_id}:{','.join(ch.conditions) if ch.conditions else 'ok'}"
                for ch in characters
            ),
        )
        .build()
    )
    return compile_baresexp(task, mode=mode)


# ── Decoders ──


def decode_location_summary(baresexp_str: str) -> dict[str, Any]:
    """Decode a location baresexp back to a summary dict (not full LocationNode).

    Used for reading compact summaries of background locations.
    """
    parsed = parse_baresexp(baresexp_str)
    summary: dict[str, Any] = {}
    if hasattr(parsed, "name"):
        summary["id"] = parsed.name.replace("location:", "")
    for step in getattr(parsed, "steps", []):
        summary[step.name] = step.description
    return summary


def decode_pool_summary(baresexp_str: str) -> dict[str, Any]:
    """Decode a pool baresexp back to a summary dict."""
    parsed = parse_baresexp(baresexp_str)
    summary: dict[str, Any] = {}
    for step in getattr(parsed, "steps", []):
        summary[step.name] = step.description
    return summary


# ── Helpers ──


def _flatten_dict(d: dict, prefix: str = "") -> str:
    """Flatten a nested dict into a compact string for baresexp."""
    parts = []
    for k, v in d.items():
        key = f"{prefix}.{k}" if prefix else k
        if isinstance(v, dict):
            parts.append(_flatten_dict(v, key))
        elif isinstance(v, list):
            parts.append(f"{key}=[{','.join(str(x) for x in v)}]")
        else:
            parts.append(f"{key}={v}")
    return "|".join(parts)


def total_token_count(results: list[BareSexpResult]) -> int:
    """Sum token count across multiple baresexp results."""
    return sum(r.token_count for r in results)


# ── DM Prompt Builder ──


def build_dm_prompt(
    pool: ActionPool,
    location: LocationNode,
    characters: list[Character],
    mode: str = "minimal",
) -> tuple[str, int]:
    """Build a full BareSexp DM prompt with context + task chained together.

    Uses builder.context() for the DM role/persona/constraints/facts,
    then builder.task() with steps for the resolution pipeline,
    followed by raw encoded state data.

    Returns (baresexp_string, token_count).
    """
    # Build character summaries
    char_parts = []
    for ch in characters:
        score = calculate_reaction_score(ch)
        parts = [f"{ch.id}({ch.name})"]
        parts.append(f"type={ch.type}")
        parts.append(f"q={ch.quickness}")
        parts.append(f"score={score:.0f}")
        if ch.conditions:
            parts.append(f"conds={','.join(ch.conditions)}")
        if ch.personality:
            parts.append(f"personality={ch.personality[:80]}")
        if ch.goals:
            parts.append(f"goals={','.join(ch.goals)}")
        if ch.secrets:
            parts.append(f"secrets={','.join(ch.secrets)}")
        char_parts.append(" ".join(parts))

    # Build action list
    action_parts = []
    for a in pool.actions:
        part = f"{a.character_id}: {a.intent}"
        if a.focused:
            part += " (focused)"
        action_parts.append(part)

    # Location context
    loc_conditions = ",".join(location.environment.conditions) if location.environment.conditions else "clean"
    loc_flags = ",".join(f"{k}={v}" for k, v in location.environment.flags.items()) if location.environment.flags else ""

    # Chain context + task using the builder
    context_result = (
        builder
        .minimal()
        .context(
            name="dungeon-master",
            role="You are a Dungeon Master resolving character actions in a text-based RPG. "
                 "Interpret combined intentions, detect contradictions, and produce outcomes "
                 "as structured JSON with resolved_actions, narrative, and world_notes.",
            domain="fantasy-roleplay-simulation",
        )
        .constraint("Return ONLY valid JSON — no markdown, no code blocks, no explanation outside JSON")
        .constraint("JSON must have keys: resolved_actions (array), narrative (string), world_notes (string)")
        .constraint("Each resolved_action needs: character_id, intent, success_level (critical|success|partial|failure|critical_failure), effects (array), description")
        .constraint("Each effect needs: target_type (location|character|world|edge), target_id, changes (dict), description")
        .constraint("Success levels should reflect action difficulty and character capability")
        .constraint("Contradictory actions can partially succeed or both fail — use your judgment")
        .fact(f"Location: {location.name} — conditions=[{loc_conditions}]")
        .fact(f"Location description: {location.description[:150]}")
        .fact(f"Round: {pool.round}")
        .fact(f"Actions to resolve: {'; '.join(action_parts) if action_parts else 'none'}")
        .task(
            name="resolve-pool",
            description=f"Resolve {len(pool.actions)} action(s) at {location.id}",
        )
        .step("gather-context", description=f"State: {loc_conditions}{' | '+loc_flags if loc_flags else ''}")
        .step("interpret-intentions", description="Analyze contradictions, synergies, independence")
        .step("apply-judgment", description="Consider personality, goals, quickness, conditions")
        .step("emit-effects", description="Produce Effects as target_type+target_id+changes for each action")
        .step("narrate", description="Write concise narrative of what actually happened")
        .compile(mode=mode)
    )

    # Attach raw encoded objects as additional context
    data_results: list[BareSexpResult] = [
        encode_location(location, mode=mode),
        encode_pool(pool, mode=mode),
    ]
    for ch in characters:
        data_results.append(encode_character(ch, mode=mode))

    data_baresexp = "\n".join(r.baresexp for r in data_results)
    data_tokens = total_token_count(data_results)

    # Combine: system prompt (context+task) + raw data
    combined = context_result.baresexp + "\n\n;; Raw encoded state\n" + data_baresexp
    total_tokens = context_result.token_count + data_tokens

    return combined, total_tokens
