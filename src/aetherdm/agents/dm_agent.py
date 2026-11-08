"""DM Agent — LangGraph node for pool resolution (Phase 0 placeholder)."""

from aetherdm.models import ActionPool, Effect


class DMAgent:
    """Dungeon Master agent for resolving action pools.

    Phase 0: Minimal placeholder — returns empty effects.
    Phase 2+: Will use LangGraph + LLM to resolve pools with narrative output.
    """

    async def resolve_pool(self, pool: ActionPool) -> list[Effect]:
        """Resolve an action pool and return a list of Effects.

        Phase 0: Returns an empty list (no-op).
        Phase 1: Will use rule-based resolution.
        Phase 2+: Will use LLM with structured output.
        """
        # TODO: Implement pool resolution logic
        return []

    def generate_narrative(self, pool: ActionPool, effects: list[Effect]) -> str:
        """Generate a narrative description of what happened.

        Phase 0: Returns a placeholder string.
        Phase 2+: Will use LLM to generate rich narrative.
        """
        return f"[Round {pool.round}] Actions resolved for location {pool.location_id}."
