"""Session manager — save and load game state snapshots."""

import json
from datetime import datetime
from pathlib import Path

from aetherdm.db.repository import Repository
from aetherdm.models import GameState


class SessionManager:
    """Manages game session persistence."""

    def __init__(self, repo: Repository):
        self.repo = repo

    def save_session(self, session_id: str, game_state: GameState) -> None:
        """Save current game state to the sessions table."""
        snapshot = {
            "current_round": game_state.current_round,
            "active_location_ids": game_state.active_location_ids,
            "global_flags": game_state.global_flags,
            "world_history": game_state.world_history,
            "saved_at": datetime.now().isoformat(),
        }
        self.repo.conn.execute(
            """INSERT OR REPLACE INTO game_sessions
               (id, seed_name, current_round, state_snapshot)
               VALUES (?, ?, ?, ?)""",
            (
                session_id,
                game_state.seed_name,
                game_state.current_round,
                json.dumps(snapshot),
            ),
        )
        self.repo.conn.commit()

    def load_session(self, session_id: str) -> GameState | None:
        """Load a saved game state from the sessions table."""
        row = self.repo.conn.execute(
            "SELECT * FROM game_sessions WHERE id = ?", (session_id,)
        ).fetchone()
        if row is None:
            return None

        snapshot = json.loads(row["state_snapshot"])
        return GameState(
            session_id=session_id,
            seed_name=row["seed_name"],
            current_round=snapshot.get("current_round", 0),
            active_location_ids=snapshot.get("active_location_ids", []),
            global_flags=snapshot.get("global_flags", {}),
            world_history=snapshot.get("world_history", []),
        )

    def list_sessions(self) -> list[dict]:
        """List all saved sessions."""
        rows = self.repo.conn.execute(
            "SELECT id, seed_name, current_round, state_snapshot FROM game_sessions"
        ).fetchall()
        result = []
        for row in rows:
            snapshot = json.loads(row["state_snapshot"])
            result.append({
                "id": row["id"],
                "seed_name": row["seed_name"],
                "round": row["current_round"],
                "saved_at": snapshot.get("saved_at", "unknown"),
            })
        return result
