"""Component seed loader — loads separate location/NPC/PC files and composes them."""

import json
from pathlib import Path

from aetherdm.db.repository import Repository
from aetherdm.models import Character, LocationNode
from aetherdm.models.seed import SeedCharacter, SeedLocation, SeedWorld
from aetherdm.seed_validator import validate_seed_data


class ComponentSeedLoader:
    """Loads a world from separate component files and composes them.

    Directory layout:
        world_dir/
        ├── world.json        # name, description, global_flags
        ├── locations/        # one JSON file per location
        ├── npcs/             # one JSON file per NPC
        └── pcs/              # one JSON file per PC
    """

    def __init__(self, repo: Repository):
        self.repo = repo

    def load(self, world_dir: Path | str) -> dict:
        """Load component files and persist to repository.

        Returns the composed seed dict.
        """
        world_dir = Path(world_dir)
        if not world_dir.is_dir():
            raise ValueError(f"World directory not found: {world_dir}")

        locations = self._load_dir(world_dir / "locations", SeedLocation)
        npcs = self._load_dir(world_dir / "npcs", SeedCharacter)
        pcs = self._load_dir(world_dir / "pcs", SeedCharacter)

        # Load world metadata
        world_file = world_dir / "world.json"
        if world_file.exists():
            with open(world_file, "r", encoding="utf-8") as f:
                world_meta = json.load(f)
        else:
            world_meta = {}

        characters = npcs + pcs

        composed = {
            "name": world_meta.get("name", world_dir.name),
            "description": world_meta.get("description", ""),
            "global_flags": world_meta.get("global_flags", {}),
            "locations": [loc.model_dump() for loc in locations],
            "characters": [ch.model_dump() for ch in characters],
        }

        # Validate the composed seed
        seed, errors = validate_seed_data(composed)
        if errors:
            error_msgs = "\n".join(f"  - {e}" for e in errors)
            raise ValueError(f"Composed seed validation failed:\n{error_msgs}")

        # Persist
        for loc_data in composed["locations"]:
            self.repo.save_location(LocationNode(**loc_data))
        for char_data in composed["characters"]:
            self.repo.save_character(Character(**char_data))

        return composed

    def _load_dir(self, dir_path: Path, model: type) -> list:
        """Load all JSON files from a directory as model instances."""
        if not dir_path.is_dir():
            return []
        results = []
        for f in sorted(dir_path.glob("*.json")):
            with open(f, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            results.append(model(**data))
        return results

    def export_components(self, seed_data: dict, output_dir: Path | str) -> None:
        """Split a monolithic seed into component files.

        Creates:
            output_dir/
            ├── world.json
            ├── locations/<id>.json
            ├── npcs/<id>.json
            └── pcs/<id>.json
        """
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        # World metadata
        world_meta = {
            "name": seed_data.get("name", "unknown"),
            "description": seed_data.get("description", ""),
            "global_flags": seed_data.get("global_flags", {}),
        }
        with open(output_dir / "world.json", "w", encoding="utf-8") as f:
            json.dump(world_meta, f, indent=2, ensure_ascii=False)

        # Locations
        loc_dir = output_dir / "locations"
        loc_dir.mkdir(exist_ok=True)
        for loc in seed_data.get("locations", []):
            with open(loc_dir / f"{loc['id']}.json", "w", encoding="utf-8") as f:
                json.dump(loc, f, indent=2, ensure_ascii=False)

        # Characters split into npcs/ and pcs/
        npc_dir = output_dir / "npcs"
        pc_dir = output_dir / "pcs"
        npc_dir.mkdir(exist_ok=True)
        pc_dir.mkdir(exist_ok=True)
        for ch in seed_data.get("characters", []):
            target_dir = npc_dir if ch["type"] == "npc" else pc_dir
            with open(target_dir / f"{ch['id']}.json", "w", encoding="utf-8") as f:
                json.dump(ch, f, indent=2, ensure_ascii=False)
