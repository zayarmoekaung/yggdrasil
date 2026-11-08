"""Game state and world-level models."""

from typing import Any

from pydantic import BaseModel, Field


class GameState(BaseModel):
    """Top-level game session state."""

    session_id: str = ""
    seed_name: str = ""
    current_round: int = 0
    active_location_ids: list[str] = Field(default_factory=list)
    global_flags: dict[str, Any] = Field(default_factory=dict)
    world_history: list[str] = Field(
        default_factory=list, description="Narrative summary of past rounds"
    )
