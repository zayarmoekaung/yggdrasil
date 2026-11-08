"""Effect data model."""

from typing import Any

from pydantic import BaseModel, Field


class Effect(BaseModel):
    """A state change emitted by a resolved Event or DM during pool resolution."""

    target_type: str = Field(..., description="location|character|world|edge")
    target_id: str
    changes: dict[str, Any] = Field(default_factory=dict, description="The actual mutations")
    description: str = Field(default="", description="For logging / DM")
