"""Simulation engine — main round loop with rule-based pool resolution."""

from aetherdm.agents.dm_agent import DMAgent
from aetherdm.baresexp_codec import encode_pool, encode_world_state
from aetherdm.db.repository import Repository
from aetherdm.models import ActionEntry, ActionPool, Character, Effect, Event, GameState, LocationNode
from aetherdm.simulation.effect_applier import apply_effect
from aetherdm.simulation.reaction import calculate_reaction_score, order_characters_by_reaction
from aetherdm.simulation.eligibility import filter_eligible


class SimulationEngine:
    """Main round loop for the simulation.

    Phase 1: Rule-based DM resolves action pools using reaction score ordering.
    Phase 2+: Integrates LangGraph DM Agent + LLM for pool resolution.

    Architecture:
    - Background locations: store baresexp summaries (compact, no LLM narration)
    - PC location: call verbose narration model after resolution
    - Transition: when PC arrives at a location with baresexp history, narrate what happened
    """

    def __init__(self, repo: Repository, use_llm: bool = True, debug: bool = False):
        self.repo = repo
        self.game_state = GameState()
        self.dm_agent = self._init_dm_agent(use_llm, debug)
        self._locations: dict[str, LocationNode] = {}
        self._characters: dict[str, Character] = {}
        # Baresexp summaries for background locations (compact storage)
        self._location_baresexp: dict[str, str] = {}
        # Verbose narrative for the PC's current location
        self._last_narrative: str = ""
        # Narratives for locations the PC just arrived at (transition narration)
        self._transition_narratives: dict[str, str] = {}
        self._last_token_count: int = 0

    def _init_dm_agent(self, use_llm: bool, debug: bool) -> DMAgent:
        """Create DM agent with LLM provider if available."""
        if use_llm:
            try:
                from aetherdm.llm.provider import LLMProvider
                llm = LLMProvider()
                return DMAgent(llm=llm, debug=debug)
            except Exception:
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

        Args:
            pool: The action pool to resolve.
            pc_location_id: If set, this location gets verbose narration.
                           Other locations are stored as baresexp summaries.

        Resolution:
        - PC location: resolve + call narrate_sync() for verbose prose
        - Background: resolve only, store baresexp summary (no narration call)
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

        # DM Agent resolves the pool (cheap model, structured output)
        resolution = self.dm_agent.resolve_pool_sync(
            pool, location, eligible
        )

        # Store results: verbose narration for PC, baresexp for background
        if is_pc_location:
            # PC location: call verbose narration model
            narrative = self.dm_agent.narrate_sync(pool, location, resolution)
            self._last_narrative = narrative
            # Clear background storage for PC location
            self._location_baresexp.pop(pool.location_id, None)
        else:
            # Background location: store baresexp summary (no narration call)
            pool_result = encode_pool(pool, mode="minimal")
            self._location_baresexp[pool.location_id] = pool_result.baresexp
            self._last_token_count = pool_result.token_count
            # Set minimal narrative for internal use
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

    def narrate_transition(self, location_id: str) -> str | None:
        """Generate verbose narration for a location the PC just arrived at.

        If the location has baresexp history from previous rounds, narrate
        what happened while the PC was away. The baresexp entry is consumed
        (removed) after narration.

        Returns:
            Narrative string, or None if no baresexp history exists.
        """
        if location_id not in self._location_baresexp:
            return None

        location = self._locations.get(location_id)
        if location is None:
            self._location_baresexp.pop(location_id, None)
            return None

        # Build a minimal pool from the baresexp for narration context
        # We don't have the actual pool, so create a synthetic one for narration
        from aetherdm.models import ActionPool, ActionEntry

        baresexp_summary = self._location_baresexp.pop(location_id)

        # Create a synthetic pool just for narration context
        synthetic_pool = ActionPool(
            location_id=location_id,
            round=self.game_state.current_round,
            status="resolved",
        )

        # Generate narration from the verbose model
        narrative = self.dm_agent.narrate_sync(
            synthetic_pool, location,
            type('DMResolution', (), {
                'resolved_actions': [],
                'narrative': f"Background activity at {location.name}.",
                'world_notes': baresexp_summary,
            })(),
        )

        self._transition_narratives[location_id] = narrative
        return narrative

    def get_transition_narrative(self, location_id: str) -> str | None:
        """Get and consume a transition narrative for a location."""
        return self._transition_narratives.pop(location_id, None)

    def get_narrative(self, pool: ActionPool, effects: list[Effect]) -> str:
        """Generate a narrative description of what happened."""
        if self._last_narrative:
            return f"[Round {pool.round}] {pool.location_id}:\n{self._last_narrative}"

        lines = [f"[Round {pool.round}] Actions resolved at {pool.location_id}:"]
        for effect in effects:
            lines.append(f"  - {effect.description}")
        return "\n".join(lines)

    def get_background_summary(self) -> str:
        """Get a compact summary of what happened at background locations.

        Returns baresexp one-liners for all non-PC locations that were resolved.
        """
        if not self._location_baresexp:
            return "(no background activity)"
        lines = []
        for loc_id, baresexp_str in self._location_baresexp.items():
            # Show first line of baresexp as a compact indicator
            first_line = baresexp_str.split("\n")[0][:80]
            lines.append(f"  {loc_id}: {first_line}")
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
