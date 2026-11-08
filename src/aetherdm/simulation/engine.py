"""Simulation engine — main round loop with rule-based pool resolution."""

from aetherdm.agents.dm_agent import DMAgent
from aetherdm.db.repository import Repository
from aetherdm.models import ActionEntry, ActionPool, Character, Effect, Event, GameState, LocationNode
from aetherdm.simulation.effect_applier import apply_effect
from aetherdm.simulation.reaction import calculate_reaction_score, order_characters_by_reaction
from aetherdm.simulation.eligibility import filter_eligible


class SimulationEngine:
    """Main round loop for the simulation.

    Phase 1: Rule-based DM resolves action pools using reaction score ordering.
    Phase 2+: Will integrate LangGraph DM Agent + LLM for pool resolution.
    """

    def __init__(self, repo: Repository):
        self.repo = repo
        self.game_state = GameState()
        self.dm_agent = DMAgent()
        self._locations: dict[str, LocationNode] = {}
        self._characters: dict[str, Character] = {}

    def start_session(self, seed_name: str) -> None:
        """Initialize a new game session from a seed."""
        self.game_state = GameState(
            session_id=f"session-{seed_name}",
            seed_name=seed_name,
            current_round=0,
        )
        self._load_world_state()

    def _load_world_state(self) -> None:
        """Load all locations and characters into in-memory dicts."""
        for loc in self.repo.load_all_locations():
            self._locations[loc.id] = loc
        for ch in self.repo.load_all_characters():
            self._characters[ch.id] = ch

    def next_round(self) -> int:
        """Advance to the next round and return the new round number."""
        self.game_state.current_round += 1
        return self.game_state.current_round

    @property
    def current_round(self) -> int:
        return self.game_state.current_round

    def create_pool(self, location_id: str) -> ActionPool:
        """Create a new open action pool for a location in the current round."""
        pool = ActionPool(
            location_id=location_id,
            round=self.game_state.current_round,
        )
        self.repo.save_action_pool(pool)
        return pool

    def add_action(self, pool: ActionPool, character_id: str, intent: str, focused: bool = False) -> ActionPool:
        """Add an action to a pool."""
        entry = ActionEntry(
            character_id=character_id,
            intent=intent,
            declared_order=len(pool.actions) + 1,
            focused=focused,
        )
        pool.actions.append(entry)
        self.repo.save_action_pool(pool)
        return pool

    def lock_pool(self, location_id: str) -> ActionPool | None:
        """Lock an existing pool for the current round."""
        pool = self.repo.load_action_pool(location_id, self.game_state.current_round)
        if pool:
            pool.status = "locked"
            self.repo.save_action_pool(pool)
        return pool

    def resolve_pool(self, pool: ActionPool) -> list[Effect]:
        """Resolve an action pool using the LLM-powered DM Agent.

        Phase 2: DM Agent receives full context (location state, characters, actions)
        and returns structured Effects + narrative via LLM. Falls back to rule-based
        if LLM is unavailable.

        Steps:
        1. Get eligible characters at the location
        2. Build context for DM Agent
        3. DM Agent resolves actions with full contextual understanding
        4. Effects are applied and logged
        5. Narrative is returned
        """
        # Get characters at this location
        location = self._locations.get(pool.location_id)
        if location is None:
            return []

        chars_at_location = [
            self._characters[ch_id]
            for ch_id in location.characters
            if ch_id in self._characters
        ]

        # Filter eligible
        eligible = filter_eligible(chars_at_location)

        # DM Agent resolves the pool
        resolution = self.dm_agent.resolve_pool_sync(pool, location, eligible)

        # Convert resolution to effects
        effects = self.dm_agent.resolution_to_effects(resolution)

        # Apply effects
        for effect in effects:
            apply_effect(effect, self.repo, self._locations, self._characters)

        # Save events/effects for history
        action_map = {a.character_id: a for a in pool.actions}
        for effect in effects:
            event = Event(
                id=f"evt-{pool.location_id}-{pool.round}-{effect.target_id}",
                round=pool.round,
                origin_location_id=pool.location_id,
                actor_id=effect.target_id,
                type="action",
                intent=action_map.get(effect.target_id).intent if effect.target_id in action_map else "",
                scope="local",
                intensity=1.0,
                effects=[effect],
            )
            self.repo.save_event(event)

        # Mark pool as resolved
        pool.status = "resolved"
        self.repo.save_action_pool(pool)

        return effects

    def get_narrative(self, pool: ActionPool, effects: list[Effect]) -> str:
        """Generate a narrative description of what happened.

        Phase 2: Uses the narrative from the DM Agent's resolution if available,
        otherwise falls back to the simple effect listing.
        """
        # Try to get the last resolution's narrative
        if hasattr(self, "_last_narrative") and self._last_narrative:
            return f"[Round {pool.round}] {pool.location_id}:\n{self._last_narrative}"

        # Fallback
        lines = [f"[Round {pool.round}] Actions resolved at {pool.location_id}:"]
        for effect in effects:
            lines.append(f"  - {effect.description}")
        return "\n".join(lines)
