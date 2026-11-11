"""BareSexp serialization codec — converts Pydantic models to/from compact s-expressions."""

import json
from typing import Any, NamedTuple

from baresexp import BareSexpBuilder, BareSexpDocument, BareSexpResult, CompileOptions, Step, builder, compile_baresexp, parse_baresexp

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


class DMPromptParts(NamedTuple):
    """Pre-compiled system prompt and user message for LLM calls."""
    system_msg: str  # context baresexp
    user_msg: str    # task baresexp + raw encoded state
    document: BareSexpDocument
    token_count: int


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


def _count_tokens(text: str) -> int:
    """Rough token count: split on whitespace and punctuation boundaries.

    This is a fast approximation — actual LLM tokenizers differ, but
    for relative comparisons (minimal vs full) it's consistent.
    """
    import re
    return len(re.findall(r'\b\w+\b|[^\s\w]', text))


# ── DM Document Builder (BareSexpDocument) ──


def build_dm_document(
    pool: ActionPool,
    location: LocationNode,
    characters: list[Character],
    output_format: str = "json",
    mode: str = "minimal",
) -> DMPromptParts:
    """Build a BareSexpDocument with context (system prompt) and task (user message).

    Uses BareSexpDocument.compile_parts() to get .context and .task separately.
    The task's content field holds raw encoded state (location + pool + characters).

    Args:
        output_format: "json" (default) or "baresexp" — controls output instructions.
        mode: "minimal" (default) or "full" — controls baresexp compactness.

    Returns:
        (BareSexpDocument, total_token_count)
    """
    # Build character summaries for context
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

    # Build action list for context
    action_parts = []
    for a in pool.actions:
        part = f"{a.character_id}: {a.intent}"
        if a.focused:
            part += " (focused)"
        action_parts.append(part)

    # Location context
    loc_conditions = ",".join(location.environment.conditions) if location.environment.conditions else "clean"

    # Build output format constraints
    if output_format == "baresexp":
        output_constraints = [
            "Return ONLY valid BareSexp — no markdown, no code blocks, no explanation outside BareSexp",
            "Use (resolution ...) with steps: resolved-actions, narrative, world-notes",
            "Each resolved-action: (action character_id intent success_level effects description)",
            "Each effect: (effect target_type target_id changes description)",
            "Success levels: critical|success|partial|failure|critical_failure",
        ]
    else:
        output_constraints = [
            "Return ONLY valid JSON — no markdown, no code blocks, no explanation outside JSON",
            "JSON must have keys: resolved_actions (array), narrative (string), world_notes (string)",
            "Each resolved_action needs: character_id, intent, success_level, effects (array), description",
            "Each effect needs: target_type (location|character|world|edge), target_id, changes (dict), description",
            "Success levels: critical|success|partial|failure|critical_failure",
            "For character changes: memory entries must be {round: int, text: str} — NOT plain strings",
            "For character changes: inventory items must be {id: str, name: str, description: str, quantity: int}",
            "For character changes: stats and relationships values must be integers",
            "For location changes: environment objects must be {id: str, name: str, description: str, quantity: int}",
            "For location changes: environment resources must be {name: str, amount: int} pairs",
        ]

    # Build JSON payload for the task content field.
    # The content field holds DATA (what to process), while description+steps hold INSTRUCTIONS (how to process it).
    # TODO: Switch from JSON to baresexp data-payload when baresexp adds a dedicated data container type
    # (currently `task` is semantically for instructions, so using it for data confuses the LLM).
    payload = json.dumps({
        "location": location.model_dump(),
        "pool": pool.model_dump(),
        "characters": [ch.model_dump() for ch in characters],
    })

    # Build instruction steps for the task
    task_steps = [
        ("read-payload", "Read the JSON-encoded location, pool, and character data in the content field"),
        ("interpret-intentions", "Analyze contradictions, synergies, independence between declared actions"),
        ("apply-judgment", "Consider personality, goals, quickness, conditions when resolving each action"),
        ("emit-effects", "Produce Effects as target_type+target_id+changes for each resolved action"),
        ("narrate", "Write concise narrative of what actually happened at this location"),
    ]

    # Build the document: minimal context + task with JSON payload
    doc = (
        BareSexpDocument()
        .minimal()
        .context(
            name="dungeon-master",
            role="You are a Dungeon Master resolving character actions in a text-based RPG. "
                 "Interpret combined intentions, detect contradictions, and produce outcomes.",
            domain="fantasy-roleplay-simulation",
            constraints=output_constraints + [
                "Contradictory actions can partially succeed or both fail — use your judgment",
                f"Location: {location.name} — conditions=[{loc_conditions}]",
                f"Round: {pool.round}",
                f"Actions to resolve: {'; '.join(action_parts) if action_parts else 'none'}",
            ],
            facts=[f"Character: {cp}" for cp in char_parts] if char_parts else ["No characters at location"],
        )
        .task(
            name="resolve-pool",
            description=(
                f"Resolve {len(pool.actions)} action(s) at {location.id}. "
                f"Read the JSON payload in the content field, follow the steps below, "
                f"and return structured output."
            ),
            content=payload,
            steps=[
                Step(name="read-payload", description="Read the JSON-encoded location, pool, and character data in the content field"),
                Step(name="interpret-intentions", description="Analyze contradictions, synergies, independence between declared actions"),
                Step(name="apply-judgment", description="Consider personality, goals, quickness, conditions when resolving each action"),
                Step(name="emit-effects", description="Produce Effects as target_type+target_id+changes for each resolved action"),
                Step(name="narrate", description="Write concise narrative of what actually happened at this location"),
            ],
        )
    )

    # Compile context in minimal mode (compact system prompt)
    ctx_result = doc.compile_context(options=CompileOptions(mode='minimal',condense=True))
    system_msg = ctx_result.baresexp

    # Compile task in full mode to preserve the JSON content verbatim
    task_result = doc.compile_task(options=CompileOptions(mode='full',condense=True))
    user_msg = task_result.baresexp

    total_tokens = _count_tokens(system_msg) + _count_tokens(user_msg)

    return DMPromptParts(
        system_msg=system_msg,
        user_msg=user_msg,
        document=doc,
        token_count=total_tokens,
    )


# ── Narration Document Builder ──


def build_narrate_document(
    location: LocationNode,
    pool: ActionPool,
    resolution_narrative: str,
    action_details: list[str],
    mode: str = "minimal",
) -> DMPromptParts:
    """Build a BareSexpDocument for the narration model call.

    Uses the same context/task split as build_dm_document for uniformity:
    - Context (minimal) → system prompt: narrator role, constraints, location facts
    - Task (full) → user message: instruction to expand resolution narrative, with
      the resolution narrative + action details as JSON content payload

    Returns:
        DMPromptParts(system_msg, user_msg, document, token_count)
    """
    loc_conditions = ",".join(location.environment.conditions) if location.environment.conditions else "calm"

    # Payload: resolution narrative + action details as structured data
    payload = json.dumps({
        "resolution_narrative": resolution_narrative,
        "action_details": action_details,
        "location": {
            "id": location.id,
            "name": location.name,
            "description": location.description,
            "conditions": location.environment.conditions,
        },
        "round": pool.round,
    })

    doc = (
        BareSexpDocument()
        .minimal()
        .context(
            name="narrator",
            role="You are a Dungeon Master writing vivid narrative prose for a text-based RPG.",
            domain="fantasy-roleplay-simulation",
            constraints=[
                "Return ONLY the narrative text — no markdown, no code blocks, no meta-commentary",
                "DO NOT invent new events, actions, or outcomes — only embellish what is given",
                "Set the scene, convey sensory details and emotions, but stay faithful to the facts",
                "Write in second person present tense where appropriate",
                "Keep it to 2-4 paragraphs",
            ],
            facts=[
                f"Location: {location.name} — conditions=[{loc_conditions}]",
                f"Round: {pool.round}",
            ],
        )
        .task(
            name="expand-narrative",
            description=(
                "Expand the resolution narrative in the content field into vivid prose. "
                "Stay faithful to every event — do not add, remove, or change outcomes."
            ),
            content=payload,
            steps=[
                Step(name="read-resolution", description="Read the resolution narrative and action details from the content field"),
                Step(name="embellish", description="Add sensory details, atmosphere, and emotional resonance without changing facts"),
                Step(name="output", description="Return the expanded narrative as plain text"),
            ],
        )
    )

    ctx_result = doc.compile_context()
    system_msg = ctx_result.baresexp

    task_result = doc.compile_task(options=CompileOptions(mode='full'))
    user_msg = task_result.baresexp

    total_tokens = _count_tokens(system_msg) + _count_tokens(user_msg)

    return DMPromptParts(
        system_msg=system_msg,
        user_msg=user_msg,
        document=doc,
        token_count=total_tokens,
    )


# ── Legacy: kept for backward compatibility ──


def build_dm_prompt(
    pool: ActionPool,
    location: LocationNode,
    characters: list[Character],
    mode: str = "minimal",
) -> tuple[str, int]:
    """Build a full BareSexp DM prompt with context + task chained together.

    Deprecated: use build_dm_document() instead, which uses BareSexpDocument
    with compile_parts() for clean system/user prompt separation.

    Returns (baresexp_string, token_count).
    """
    prompt = build_dm_document(pool, location, characters, mode=mode)
    parts = prompt.document.compile_parts()
    return parts.full, prompt.token_count
