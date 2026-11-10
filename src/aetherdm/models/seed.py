"""Pydantic seed models for validating world seed JSON files."""

from typing import Any

from pydantic import BaseModel, Field, field_validator


class SeedObject(BaseModel):
    """An object definition within a location seed."""

    id: str = Field(..., min_length=1)
    name: str = Field(..., min_length=1)
    description: str = ""
    quantity: int = Field(default=1, ge=1)


class SeedConnection(BaseModel):
    """A connection definition within a location seed."""

    target_id: str = Field(..., min_length=1)
    type: str = Field(..., description="road|path|river|portal|secret|rumor")
    travel_time: int = Field(default=1, ge=1)
    propagation_modifier: float = Field(default=1.0, ge=0.1, le=2.0)

    @field_validator("type")
    @classmethod
    def validate_connection_type(cls, v: str) -> str:
        valid = {"road", "path", "river", "portal", "secret", "rumor"}
        if v not in valid:
            raise ValueError(f"connection type must be one of {valid}, got '{v}'")
        return v


class SeedEnvironment(BaseModel):
    """Environment definition within a location seed."""

    conditions: list[str] = Field(default_factory=list)
    objects: list[SeedObject] = Field(default_factory=list)
    resources: dict[str, int] = Field(default_factory=dict)
    flags: dict[str, Any] = Field(default_factory=dict)


class SeedLocation(BaseModel):
    """A location definition in a world seed."""

    id: str = Field(..., min_length=1)
    name: str = Field(..., min_length=1)
    description: str = ""
    tags: list[str] = Field(default_factory=list)
    environment: SeedEnvironment = Field(default_factory=SeedEnvironment)
    connections: list[SeedConnection] = Field(default_factory=list)
    characters: list[str] = Field(default_factory=list)
    pending_effects: list[dict[str, Any]] = Field(default_factory=list)


class SeedCharacter(BaseModel):
    """A character definition in a world seed."""

    id: str = Field(..., min_length=1)
    name: str = Field(..., min_length=1)
    type: str = Field(..., description="pc|npc")
    location_id: str = Field(..., min_length=1)
    stats: dict[str, int] = Field(default_factory=dict)
    inventory: list[SeedObject] = Field(default_factory=list)
    personality: str = ""
    goals: list[str] = Field(default_factory=list)
    secrets: list[str] = Field(default_factory=list)
    quickness: int = Field(default=5, ge=1, le=10)
    memory: list[dict[str, Any]] = Field(default_factory=list)
    relationships: dict[str, int] = Field(default_factory=dict)
    conditions: list[str] = Field(default_factory=list)

    @field_validator("type")
    @classmethod
    def validate_character_type(cls, v: str) -> str:
        if v not in ("pc", "npc"):
            raise ValueError(f"character type must be 'pc' or 'npc', got '{v}'")
        return v

    @field_validator("relationships")
    @classmethod
    def validate_relationship_values(cls, v: dict[str, int]) -> dict[str, int]:
        for k, val in v.items():
            if val < -100 or val > 100:
                raise ValueError(
                    f"relationship value for '{k}' must be between -100 and 100, got {val}"
                )
        return v


class SeedWorld(BaseModel):
    """Top-level world seed model — validates the entire seed file."""

    name: str = Field(..., min_length=1)
    description: str = ""
    locations: list[SeedLocation] = Field(..., min_length=1)
    characters: list[SeedCharacter] = Field(..., min_length=1)
    global_flags: dict[str, Any] = Field(default_factory=dict)
