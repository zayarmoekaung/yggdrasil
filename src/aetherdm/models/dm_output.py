"""DM output models — structured output from the LLM DM Agent."""

from typing import Any

from pydantic import BaseModel, Field


class ResolvedAction(BaseModel):
    """A single action resolved by the DM."""

    character_id: str
    intent: str
    success_level: str = Field(
        ..., description="critical|success|partial|failure|critical_failure"
    )
    effects: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Effects as dict with target_type, target_id, changes, description",
    )
    description: str = Field(
        default="", description="What actually happened for this action"
    )


class DMResolution(BaseModel):
    """Full output from the DM Agent for a resolved action pool."""

    resolved_actions: list[ResolvedAction] = Field(
        default_factory=list, description="Each action in the pool with its resolution"
    )
    narrative: str = Field(
        default="", description="Concise narrative of what happened in this location"
    )
    world_notes: str = Field(
        default="",
        description="Optional notes about spreading consequences to other locations",
    )
