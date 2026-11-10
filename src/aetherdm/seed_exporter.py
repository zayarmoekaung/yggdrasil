"""Seed exporter — converts runtime game state back to seed JSON."""

import json
from pathlib import Path

from aetherdm.db.repository import Repository
from aetherdm.models import Character, LocationNode


def export_seed(
    repo: Repository,
    seed_name: str = "exported",
    description: str = "",
    global_flags: dict | None = None,
) -> dict:
    """Export the current runtime state from the repository as a seed dict.

    Args:
        repo: Connected repository with locations and characters.
        seed_name: Name for the exported seed.
        description: Description string.
        global_flags: Optional global flags to include.

    Returns:
        A dict matching the SeedWorld schema, ready to serialize as JSON.
    """
    locations = repo.load_all_locations()
    characters = repo.load_all_characters()

    seed_locations = [_location_to_seed(loc) for loc in locations]
    seed_characters = [_character_to_seed(ch) for ch in characters]

    return {
        "name": seed_name,
        "description": description,
        "global_flags": global_flags or {},
        "locations": seed_locations,
        "characters": seed_characters,
    }


def _location_to_seed(loc: LocationNode) -> dict:
    """Convert a runtime LocationNode to a seed-compatible dict."""
    return {
        "id": loc.id,
        "name": loc.name,
        "description": loc.description,
        "tags": loc.tags,
        "environment": {
            "conditions": loc.environment.conditions,
            "objects": [
                {
                    "id": obj.id,
                    "name": obj.name,
                    "description": obj.description,
                    "quantity": obj.quantity,
                }
                for obj in loc.environment.objects
            ],
            "resources": loc.environment.resources,
            "flags": loc.environment.flags,
        },
        "connections": [
            {
                "target_id": c.target_id,
                "type": c.type,
                "travel_time": c.travel_time,
                "propagation_modifier": c.propagation_modifier,
            }
            for c in loc.connections
        ],
        "characters": loc.characters,
        "pending_effects": [],
    }


def _character_to_seed(ch: Character) -> dict:
    """Convert a runtime Character to a seed-compatible dict."""
    return {
        "id": ch.id,
        "name": ch.name,
        "type": ch.type,
        "location_id": ch.location_id,
        "stats": ch.stats,
        "inventory": [
            {
                "id": item.id,
                "name": item.name,
                "description": item.description,
                "quantity": item.quantity,
            }
            for item in ch.inventory
        ],
        "personality": ch.personality,
        "goals": ch.goals,
        "secrets": ch.secrets,
        "quickness": ch.quickness,
        "memory": [m.model_dump() for m in ch.memory],
        "relationships": ch.relationships,
        "conditions": ch.conditions,
    }


def export_seed_to_file(
    repo: Repository,
    output_path: Path | str,
    seed_name: str = "exported",
    description: str = "",
    global_flags: dict | None = None,
) -> None:
    """Export runtime state to a seed JSON file."""
    seed_data = export_seed(repo, seed_name, description, global_flags)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(seed_data, f, indent=2, ensure_ascii=False)
