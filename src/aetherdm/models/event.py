"""Event and effect data models."""

from typing import Any

from pydantic import BaseModel, Field


class Effect(BaseModel):
    """A state change emitted by a resolved Event or DM during pool resolution."""

    target_type: str = Field(..., description="location|character|world|edge")
    target_id: str
    changes: dict[str, Any] = Field(default_factory=dict, description="The actual mutations")
    description: str = Field(default="", description="For logging / DM")


class MechanicalResult(BaseModel):
    """Optional mechanical resolution data for an event."""

    success_level: str | None = Field(
        default=None, description="critical|success|partial|failure|critical_failure"
    )
    dice: dict[str, Any] | None = None
    tags: list[str] = Field(default_factory=list)


class Event(BaseModel):
    """A resolved event in the simulation."""

    id: str
    round: int
    time_token: int = Field(default=0, description="Optional finer ordering inside a round")

    origin_location_id: str
    actor_id: str = Field(..., description="character id, 'world', or 'dm'")

    type: str = Field(..., description="action|mutation|perception|system")
    intent: str = Field(default="", description="Human-readable declared intention")
    intensity: float = Field(default=1.0, ge=0.0, description="0.0 - 10.0+")

    # Propagation
    scope: str = Field(..., description="local|adjacent|region|global")
    remaining_intensity: float = Field(default=1.0)

    # Resolution
    mechanical: MechanicalResult | None = None

    effects: list[Effect] = Field(default_factory=list)
    visibility: str = Field(
        default="public", description="public|local|private|secret"
    )

    model_config = {"json_schema_extra": {"required": ["id", "round", "origin_location_id", "actor_id", "type", "scope"]}}
