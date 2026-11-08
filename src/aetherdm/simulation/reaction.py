"""Reaction Score calculation — orders characters by how fast they respond to events."""

from aetherdm.models import Character

# Penalty multipliers for common conditions
_CONDITION_PENALTIES: dict[str, float] = {
    "panicked": 0.6,
    "alarmed": 0.8,
    "wounded": 0.7,
    "stunned": 0.3,
    "paralyzed": 0.0,
    "asleep": 0.1,
    "hidden": 1.0,  # hidden characters react at normal speed
}


def calculate_reaction_score(character: Character) -> float:
    """Calculate a character's reaction score for the current round.

    Base score = quickness (1-10)
    Modified by condition penalties (multiplicative)
    Higher score = faster reaction = higher priority in action ordering.
    """
    score = float(character.quickness)

    for condition in character.conditions:
        penalty = _CONDITION_PENALTIES.get(condition, 1.0)
        score *= penalty

    return score


def order_characters_by_reaction(characters: list[Character]) -> list[Character]:
    """Sort characters by reaction score descending (highest = acts first)."""
    scored = [(ch, calculate_reaction_score(ch)) for ch in characters]
    scored.sort(key=lambda x: x[1], reverse=True)
    return [ch for ch, _ in scored]
