"""Seed validation — Pydantic schema validation + cross-reference checks."""

import json
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from aetherdm.models.seed import SeedWorld


class SeedValidationError:
    """A single validation error found in a seed file."""

    def __init__(self, field: str, message: str):
        self.field = field
        self.message = message

    def __str__(self) -> str:
        return f"[{self.field}] {self.message}"


def validate_seed(seed_path: Path | str) -> tuple[SeedWorld | None, list[SeedValidationError]]:
    """Validate a seed JSON file.

    Returns:
        (parsed_seed, errors) — parsed_seed is None if schema validation fails.
    """
    errors: list[SeedValidationError] = []
    seed_path = Path(seed_path)

    # Step 1: JSON parse
    try:
        raw = seed_path.read_text(encoding="utf-8")
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        return None, [SeedValidationError("json", f"Invalid JSON: {e}")]
    except FileNotFoundError:
        return None, [SeedValidationError("file", f"File not found: {seed_path}")]

    # Step 2: Pydantic schema validation
    try:
        seed = SeedWorld(**data)
    except ValidationError as e:
        for err in e.errors():
            loc = ".".join(str(x) for x in err["loc"]) if err.get("loc") else "seed"
            errors.append(SeedValidationError(loc, err["msg"]))
        return None, errors

    # Step 3: Cross-reference checks
    errors.extend(_check_cross_refs(seed))
    return seed, errors


def _check_cross_refs(seed: SeedWorld) -> list[SeedValidationError]:
    """Check that all references in the seed point to valid entities."""
    errors: list[SeedValidationError] = []

    loc_ids = {loc.id for loc in seed.locations}
    char_ids = {ch.id for ch in seed.characters}

    # Check for duplicate IDs
    _check_duplicates("location", [loc.id for loc in seed.locations], errors)
    _check_duplicates("character", [ch.id for ch in seed.characters], errors)

    # Check character location_id references
    for ch in seed.characters:
        if ch.location_id not in loc_ids:
            errors.append(
                SeedValidationError(
                    f"characters.{ch.id}.location_id",
                    f"references location '{ch.location_id}' which does not exist",
                )
            )

    # Check location connection target references
    for loc in seed.locations:
        for conn in loc.connections:
            if conn.target_id not in loc_ids:
                errors.append(
                    SeedValidationError(
                        f"locations.{loc.id}.connections",
                        f"connection target '{conn.target_id}' does not exist",
                    )
                )

    # Check relationship references
    for ch in seed.characters:
        for rel_id in ch.relationships:
            if rel_id not in char_ids:
                errors.append(
                    SeedValidationError(
                        f"characters.{ch.id}.relationships",
                        f"references character '{rel_id}' which does not exist",
                    )
                )

    # Check location character references
    for loc in seed.locations:
        for ch_id in loc.characters:
            if ch_id not in char_ids:
                errors.append(
                    SeedValidationError(
                        f"locations.{loc.id}.characters",
                        f"references character '{ch_id}' which does not exist",
                    )
                )

    # Check for self-connections
    for loc in seed.locations:
        for conn in loc.connections:
            if conn.target_id == loc.id:
                errors.append(
                    SeedValidationError(
                        f"locations.{loc.id}.connections",
                        f"location connects to itself",
                    )
                )

    return errors


def _check_duplicates(
    entity_type: str, ids: list[str], errors: list[SeedValidationError]
) -> None:
    """Check for duplicate IDs in a list."""
    seen: dict[str, int] = {}
    for id_ in ids:
        seen[id_] = seen.get(id_, 0) + 1
    for id_, count in seen.items():
        if count > 1:
            errors.append(
                SeedValidationError(
                    f"{entity_type}.{id_}",
                    f"duplicate {entity_type} id (appears {count} times)",
                )
            )


def validate_seed_data(data: dict[str, Any]) -> tuple[SeedWorld | None, list[SeedValidationError]]:
    """Validate a seed dict (already parsed from JSON)."""
    errors: list[SeedValidationError] = []

    try:
        seed = SeedWorld(**data)
    except ValidationError as e:
        for err in e.errors():
            loc = ".".join(str(x) for x in err["loc"]) if err.get("loc") else "seed"
            errors.append(SeedValidationError(loc, err["msg"]))
        return None, errors

    errors.extend(_check_cross_refs(seed))
    return seed, errors
