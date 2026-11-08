"""Action pool data models."""

from pydantic import BaseModel, Field


class ActionEntry(BaseModel):
    """A single declared action in a pool."""

    character_id: str
    intent: str
    declared_order: int = Field(default=0, description="Position in the declaration sequence")
    reaction_to: list[str] = Field(
        default_factory=list, description="Event ids this was responding to"
    )
    focused: bool = Field(
        default=False, description="True = reacted to single highest event"
    )


class ActionPool(BaseModel):
    """Collection of actions for a location/round."""

    location_id: str
    round: int
    actions: list[ActionEntry] = Field(default_factory=list)
    status: str = Field(default="open", description="open|locked|resolved")

    model_config = {"json_schema_extra": {"required": ["location_id", "round"]}}
