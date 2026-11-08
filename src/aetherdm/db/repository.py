"""Repository layer for SQLite persistence."""

import json
import sqlite3
from pathlib import Path
from typing import Any

from aetherdm.models import (
    ActionEntry,
    ActionPool,
    Character,
    Connection,
    Effect,
    Environment,
    Event,
    LocationNode,
)


class Repository:
    """SQLite-backed repository for all game entities."""

    def __init__(self, db_path: Path | str):
        self.db_path = Path(db_path)
        self._conn: sqlite3.Connection | None = None

    def connect(self) -> None:
        self._conn = sqlite3.connect(str(self.db_path))
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            raise RuntimeError("Repository not connected. Call connect() first.")
        return self._conn

    def _init_schema(self) -> None:
        schema_path = Path(__file__).parent / "schema.sql"
        self.conn.executescript(schema_path.read_text())

    # -- Location operations --

    def save_location(self, location: LocationNode) -> None:
        self.conn.execute(
            """INSERT OR REPLACE INTO locations
               (id, name, description, tags, environment, flags, last_mutated_round)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                location.id,
                location.name,
                location.description,
                json.dumps(location.tags),
                json.dumps(location.environment.model_dump()),
                json.dumps({}),
                location.last_mutated_round,
            ),
        )
        # Save connections
        for c in location.connections:
            self.conn.execute(
                """INSERT OR REPLACE INTO location_connections
                   (from_id, to_id, type, travel_time, propagation_modifier)
                   VALUES (?, ?, ?, ?, ?)""",
                (
                    location.id,
                    c.target_id,
                    c.type,
                    c.travel_time,
                    c.propagation_modifier,
                ),
            )
        self.conn.commit()

    def load_location(self, location_id: str) -> LocationNode | None:
        row = self.conn.execute(
            "SELECT * FROM locations WHERE id = ?", (location_id,)
        ).fetchone()
        if row is None:
            return None
        env_data = json.loads(row["environment"])
        connections = self.load_connections(location_id)
        characters = self.load_character_ids_at(location_id)
        return LocationNode(
            id=row["id"],
            name=row["name"],
            description=row["description"],
            tags=json.loads(row["tags"]),
            environment=Environment(**env_data),
            connections=connections,
            characters=characters,
            last_mutated_round=row["last_mutated_round"],
        )

    def load_character_ids_at(self, location_id: str) -> list[str]:
        """Get character IDs currently at a location (from characters.location_id)."""
        rows = self.conn.execute(
            "SELECT id FROM characters WHERE location_id = ?", (location_id,)
        ).fetchall()
        return [r["id"] for r in rows]

    def load_all_locations(self) -> list[LocationNode]:
        rows = self.conn.execute("SELECT * FROM locations").fetchall()
        result = []
        for row in rows:
            loc = self.load_location(row["id"])
            if loc is not None:
                result.append(loc)
        return result

    def load_connections(self, location_id: str) -> list[Connection]:
        rows = self.conn.execute(
            "SELECT * FROM location_connections WHERE from_id = ?", (location_id,)
        ).fetchall()
        return [
            Connection(
                target_id=r["to_id"],
                type=r["type"],
                travel_time=r["travel_time"],
                propagation_modifier=r["propagation_modifier"],
            )
            for r in rows
        ]

    # -- Character operations --

    def save_character(self, character: Character) -> None:
        self.conn.execute(
            """INSERT OR REPLACE INTO characters
               (id, name, type, location_id, stats, inventory, personality,
                goals, secrets, quickness, memory, relationships, conditions,
                last_action_round, current_plan)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                character.id,
                character.name,
                character.type,
                character.location_id,
                json.dumps(character.stats),
                json.dumps([i.model_dump() for i in character.inventory]),
                character.personality,
                json.dumps(character.goals),
                json.dumps(character.secrets),
                character.quickness,
                json.dumps([m.model_dump() for m in character.memory]),
                json.dumps(character.relationships),
                json.dumps(character.conditions),
                character.last_action_round,
                character.current_plan,
            ),
        )
        self.conn.commit()

    def load_character(self, character_id: str) -> Character | None:
        row = self.conn.execute(
            "SELECT * FROM characters WHERE id = ?", (character_id,)
        ).fetchone()
        if row is None:
            return None
        return self._row_to_character(row)

    def load_all_characters(self) -> list[Character]:
        rows = self.conn.execute("SELECT * FROM characters").fetchall()
        return [self._row_to_character(r) for r in rows]

    def _row_to_character(self, row: sqlite3.Row) -> Character:
        from aetherdm.models.character import Item, MemoryEntry

        return Character(
            id=row["id"],
            name=row["name"],
            type=row["type"],
            location_id=row["location_id"],
            stats=json.loads(row["stats"]),
            inventory=[Item(**d) for d in json.loads(row["inventory"])],
            personality=row["personality"],
            goals=json.loads(row["goals"]),
            secrets=json.loads(row["secrets"]),
            quickness=row["quickness"],
            memory=[MemoryEntry(**d) for d in json.loads(row["memory"])],
            relationships=json.loads(row["relationships"]),
            conditions=json.loads(row["conditions"]),
            last_action_round=row["last_action_round"],
            current_plan=row["current_plan"],
        )

    # -- Action Pool operations --

    def save_action_pool(self, pool: ActionPool) -> None:
        self.conn.execute(
            """INSERT OR REPLACE INTO action_pools
               (location_id, round, status, actions)
               VALUES (?, ?, ?, ?)""",
            (
                pool.location_id,
                pool.round,
                pool.status,
                json.dumps([a.model_dump() for a in pool.actions]),
            ),
        )
        self.conn.commit()

    def load_action_pool(self, location_id: str, round_num: int) -> ActionPool | None:
        row = self.conn.execute(
            "SELECT * FROM action_pools WHERE location_id = ? AND round = ?",
            (location_id, round_num),
        ).fetchone()
        if row is None:
            return None
        actions = [ActionEntry(**d) for d in json.loads(row["actions"])]
        return ActionPool(
            location_id=row["location_id"],
            round=row["round"],
            actions=actions,
            status=row["status"],
        )

    # -- Event / Effect operations (history / debugging) --

    def save_event(self, event: Event) -> None:
        mechanical_json = json.dumps(event.mechanical.model_dump()) if event.mechanical else None
        self.conn.execute(
            """INSERT OR REPLACE INTO events
               (id, round, time_token, origin_location_id, actor_id, type,
                intent, intensity, scope, remaining_intensity, mechanical, visibility)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                event.id,
                event.round,
                event.time_token,
                event.origin_location_id,
                event.actor_id,
                event.type,
                event.intent,
                event.intensity,
                event.scope,
                event.remaining_intensity,
                mechanical_json,
                event.visibility,
            ),
        )
        for effect in event.effects:
            self.conn.execute(
                """INSERT INTO effects
                   (event_id, target_type, target_id, changes, description)
                   VALUES (?, ?, ?, ?, ?)""",
                (
                    event.id,
                    effect.target_type,
                    effect.target_id,
                    json.dumps(effect.changes),
                    effect.description,
                ),
            )
        self.conn.commit()
