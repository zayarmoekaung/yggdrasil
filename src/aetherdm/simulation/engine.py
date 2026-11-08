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
        """Resolve an action pool using rule-based logic.

        Phase 1: All actions are processed in reaction-score order.
        Each eligible character's action succeeds. Contradiction detection
        is intentionally NOT done here — that is the DM Agent's job in Phase 2,
        where the LLM has full context to judge whether actions conflict.

        Steps:
        1. Get eligible characters at the location
        2. Order by reaction score (higher = acts first)
        3. Each action produces an Effect
        4. Effects are applied and logged
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

        # Filter eligible and order by reaction
        eligible = filter_eligible(chars_at_location)
        ordered = order_characters_by_reaction(eligible)

        # Build action lookup (only for characters who declared actions)
        action_map = {a.character_id: a for a in pool.actions}

        effects: list[Effect] = []
        for ch in ordered:
            action = action_map.get(ch.id)
            if action is None:
                continue
            effect = self._create_effect_for_action(action)
            effects.append(effect)

        # Apply effects
        for effect in effects:
            apply_effect(effect, self.repo, self._locations, self._characters)

        # Save events/effects for history
        for effect in effects:
            event = Event(
                id=f"evt-{pool.location_id}-{pool.round}-{effect.target_id}",
                round=pool.round,
                origin_location_id=pool.location_id,
                actor_id=effect.target_id,
                type="action",
                intent=action_map[effect.target_id].intent if effect.target_id in action_map else "",
                scope="local",
                intensity=1.0,
                effects=[effect],
            )
            self.repo.save_event(event)

        # Mark pool as resolved
        pool.status = "resolved"
        self.repo.save_action_pool(pool)

        return effects

    def _create_effect_for_action(self, action: ActionEntry) -> Effect:
        """Create an Effect representing a successful action.

        Phase 1: Simple placeholder effect that adds a condition to the character.
        Phase 2+: Will parse intent and generate meaningful effects.
        """
        return Effect(
            target_type="character",
            target_id=action.character_id,
            changes={"conditions": ["acted"]},
            description=f"{action.character_id} successfully: {action.intent}",
        )

    def get_narrative(self, pool: ActionPool, effects: list[Effect]) -> str:
        """Generate a narrative description of what happened."""
        lines = [f"[Round {pool.round}] Actions resolved at {pool.location_id}:"]
        for effect in effects:
            lines.append(f"  - {effect.description}")
        return "\n".join(lines)
