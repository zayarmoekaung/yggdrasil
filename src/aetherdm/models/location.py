"""Location data models."""

from typing import Any

from pydantic import BaseModel, Field


class Connection(BaseModel):
    """A connection between two locations."""

    target_id: str
    type: str = Field(..., description="road|path|river|portal|secret|rumor")
    travel_time: int = Field(default=1, description="Base time cost to traverse")
    propagation_modifier: float = Field(
        default=1.0, ge=0.1, le=2.0, description="How easily events propagate (0.1-2.0)"
    )


class Environment(BaseModel):
    """Local environment state for a location."""

    conditions: list[str] = Field(default_factory=list)
    objects: list["ObjectInstance"] = Field(default_factory=list)
    resources: dict[str, int] = Field(default_factory=dict)
    flags: dict[str, Any] = Field(default_factory=dict)


class ObjectInstance(BaseModel):
    """An object present in a location."""

    id: str
    name: str
    description: str = ""
    quantity: int = 1


class LocationNode(BaseModel):
    """A location in the world graph."""

    id: str
    name: str
    description: str = Field(default="", description="Short base description")
    tags: list[str] = Field(default_factory=list)

    # Spatial
    connections: list[Connection] = Field(default_factory=list)

    # Local state
    environment: Environment = Field(default_factory=Environment)

    # Occupants — character IDs currently here
    characters: list[str] = Field(default_factory=list)

    # Simulation
    last_mutated_round: int = 0
    # Pending effects are stored separately at runtime; this field is for seed/serialization
    pending_effects: list["Effect"] = Field(default_factory=list)

    model_config = {"json_schema_extra": {"required": ["id", "name"]}}


# Forward reference resolution (done at module load time for Effect import)
# This will be resolved after Effect is defined in effect.py
# We use a string annotation here; the actual resolution happens in __init__.py
