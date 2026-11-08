"""Character data models (PC and NPC share the same base)."""

from typing import Any

from pydantic import BaseModel, Field


class Item(BaseModel):
    """An item in a character's inventory."""

    id: str
    name: str
    description: str = ""
    quantity: int = 1


class MemoryEntry(BaseModel):
    """A short rolling memory entry for a character."""

    round: int
    text: str


class Character(BaseModel):
    """Base character model — used for both PCs and NPCs."""

    id: str
    name: str
    type: str = Field(..., description="pc|npc")

    # Core
    location_id: str
    stats: dict[str, int] = Field(default_factory=dict)
    inventory: list[Item] = Field(default_factory=list)
    conditions: list[str] = Field(default_factory=list)

    # Agency
    personality: str = Field(default="", description="Short high-signal description")
    goals: list[str] = Field(default_factory=list)
    secrets: list[str] = Field(default_factory=list)
    quickness: int = Field(
        default=5, ge=1, le=10, description="Used in Reaction Score (higher = faster)"
    )

    # Memory & Relationship
    memory: list[MemoryEntry] = Field(default_factory=list)
    relationships: dict[str, int] = Field(
        default_factory=dict, description="characterId -> disposition (-100 to 100)"
    )

    # Runtime
    last_action_round: int = 0
    current_plan: str | None = None

    model_config = {"json_schema_extra": {"required": ["id", "name", "type", "location_id"]}}
