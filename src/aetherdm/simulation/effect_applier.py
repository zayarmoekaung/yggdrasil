"""Effect Applier — applies Effects to LocationNode or Character state."""

from typing import Any

from aetherdm.db.repository import Repository
from aetherdm.models import Character, Effect, LocationNode


def _apply_changes_to_dict(data: dict[str, Any], changes: dict[str, Any]) -> None:
    """Recursively apply changes to a nested dict."""
    for key, value in changes.items():
        if isinstance(value, dict) and isinstance(data.get(key), dict):
            _apply_changes_to_dict(data[key], value)
        else:
            data[key] = value


def apply_effect(
    effect: Effect,
    repo: Repository,
    locations: dict[str, LocationNode],
    characters: dict[str, Character],
) -> None:
    """Apply an effect's changes to the appropriate target in-memory.

    After applying, persists the mutated entity via the repository.

    Supported target_types: location, character, world, edge.
    """
    if effect.target_type == "location":
        target = locations.get(effect.target_id)
        if target is None:
            return
        # Apply changes to location fields
        location_data = target.model_dump()
        _apply_changes_to_dict(location_data, effect.changes)
        # Rebuild the LocationNode from mutated data
        updated = LocationNode(**location_data)
        locations[effect.target_id] = updated
        repo.save_location(updated)

    elif effect.target_type == "character":
        target = characters.get(effect.target_id)
        if target is None:
            return
        char_data = target.model_dump()
        _apply_changes_to_dict(char_data, effect.changes)
        updated = Character(**char_data)
        characters[effect.target_id] = updated
        repo.save_character(updated)

    elif effect.target_type == "world":
        # World-level effects are logged but not persisted to a specific entity
        # (Phase 3+ will handle global_flags in GameState)
        pass

    elif effect.target_type == "edge":
        # Edge effects modify connection properties between locations
        # Format: changes should include "from_id", "to_id", and the fields to change
        from_id = effect.changes.get("from_id")
        to_id = effect.changes.get("to_id")
        if from_id and to_id and from_id in locations:
            loc = locations[from_id]
            for conn in loc.connections:
                if conn.target_id == to_id:
                    changes_copy = {
                        k: v for k, v in effect.changes.items() if k not in ("from_id", "to_id")
                    }
                    conn_data = conn.model_dump()
                    _apply_changes_to_dict(conn_data, changes_copy)
                    # Update the connection in place
                    from aetherdm.models import Connection
                    idx = loc.connections.index(conn)
                    loc.connections[idx] = Connection(**conn_data)
                    repo.save_location(loc)
                    break
