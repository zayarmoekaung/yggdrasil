"""Eligibility logic — determines which characters can act given their state."""

from aetherdm.models import Character

# Conditions that prevent a character from taking any action
_BLOCKING_CONDITIONS: set[str] = {
    "paralyzed",
    "unconscious",
    "dead",
    "petrified",
    "restrained",
}


def is_eligible(character: Character) -> bool:
    """Check if a character is eligible to act in the current round.

    A character is ineligible if they have any blocking condition.
    """
    for condition in character.conditions:
        if condition in _BLOCKING_CONDITIONS:
            return False
    return True


def filter_eligible(characters: list[Character]) -> list[Character]:
    """Return only characters who are eligible to act."""
    return [ch for ch in characters if is_eligible(ch)]
