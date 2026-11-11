"""Simulation engine — main round loop with rule-based pool resolution."""

from aetherdm.agents.dm_agent import DMAgent
from aetherdm.baresexp_codec import encode_world_state
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

    def __init__(self, repo: Repository, use_llm: bool = True, debug: bool = False):
        self.repo = repo
        self.game_state = GameState()
        self.dm_agent = self._init_dm_agent(use_llm, debug)
        self._locations: dict[str, LocationNode] = {}
        self._characters: dict[str, Character] = {}
        # Narrative summaries for background locations (readable one-liners)
        self._location_narratives: dict[str, str] = {}
        self._last_narrative: str = ""
        self._last_token_count: int = 0

    def _init_dm_agent(self, use_llm: bool, debug: bool) -> DMAgent:
        """Create DM agent with LLM provider if available."""
        if use_llm:
            try:
                from aetherdm.llm.provider import LLMProvider
                llm = LLMProvider()
                return DMAgent(llm=llm, debug=debug)
            except Exception:
                # Fall back to rule-based if LLM provider can't be initialized
                pass
        return DMAgent(debug=debug)

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

    def resolve_pool(
        self,
        pool: ActionPool,
        pc_location_id: str | None = None,
    ) -> list[Effect]:
        """Resolve an action pool using the LLM-powered DM Agent.

        Phase 2: DM Agent receives full context (location state, characters, actions)
        and returns structured Effects + narrative via LLM. Falls back to rule-based
        if LLM is unavailable.

        Args:
            pool: The action pool to resolve.
            pc_location_id: If set, this location gets verbose narration.
                           Other locations are resolved silently with compact baresexp storage.

        Steps:
        1. Get eligible characters at the location
        2. Build context for DM Agent (baresexp for fewer tokens)
        3. DM Agent resolves actions with full contextual understanding
        4. Effects are applied and logged
        5. Narrative is returned (verbose for PC location, compact for others)
        """
        # Guard against double-resolution
        if pool.status in ("locked", "resolved"):
            if pool.status == "resolved":
                return []

        # Deduplicate actions: keep only unique (character_id, intent) pairs
        seen: set[tuple[str, str]] = set()
        unique_actions: list[ActionEntry] = []
        for a in pool.actions:
            key = (a.character_id, a.intent)
            if key not in seen:
                seen.add(key)
                unique_actions.append(a)
        if len(unique_actions) < len(pool.actions):
            pool.actions = unique_actions
            self.repo.save_action_pool(pool)

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

        # Determine if this is the PC's location (verbose) or background (compact)
        is_pc_location = pc_location_id is None or pool.location_id == pc_location_id

        # DM Agent resolves the pool — use baresexp for context (fewer tokens)
        resolution = self.dm_agent.resolve_pool_sync(
            pool, location, eligible, use_baresexp=True
        )

        # Store narrative: verbose for PC location, compact summary for others
        if is_pc_location:
            self._last_narrative = resolution.narrative
            # Clear background narrative for PC location
            self._location_narratives.pop(pool.location_id, None)
        else:
            # Background location: store a concise narrative summary
            self._location_narratives[pool.location_id] = resolution.narrative
            self._last_narrative = resolution.narrative

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
        # Use the narrative stored by resolve_pool
        if hasattr(self, "_last_narrative") and self._last_narrative:
            return f"[Round {pool.round}] {pool.location_id}:\n{self._last_narrative}"

        # Fallback
        lines = [f"[Round {pool.round}] Actions resolved at {pool.location_id}:"]
        for effect in effects:
            lines.append(f"  - {effect.description}")
        return "\n".join(lines)

    def get_background_summary(self) -> str:
        """Get a compact summary of what happened at background locations.

        Returns readable one-line summaries for all non-PC locations that were resolved.
        """
        if not self._location_narratives:
            return "(no background activity)"
        lines = []
        for loc_id, summary in self._location_narratives.items():
            lines.append(f"  {loc_id}: {summary}")
        return "\n".join(lines)

    def get_world_baresexp(self) -> tuple[str, int]:
        """Encode the entire world state as compact baresexp.

        Returns (baresexp_string, token_count).
        Useful for save/load or sending to the DM as full context.
        """
        locations = list(self._locations.values())
        characters = list(self._characters.values())
        result = encode_world_state(locations, characters, self.game_state.current_round)
        return result.baresexp, result.token_count
