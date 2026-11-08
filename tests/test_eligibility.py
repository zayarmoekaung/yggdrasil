"""Tests for eligibility logic."""

import pytest

from aetherdm.models import Character
from aetherdm.simulation.eligibility import is_eligible, filter_eligible


class TestIsEligible:
    def test_eligible_by_default(self):
        ch = Character(id="hero", name="Hero", type="pc", location_id="town")
        assert is_eligible(ch) is True

    def test_eligible_with_nonblocking_conditions(self):
        ch = Character(
            id="hero", name="Hero", type="pc", location_id="town",
            conditions=["panicked", "alarmed", "wounded"],
        )
        assert is_eligible(ch) is True

    @pytest.mark.parametrize("condition", [
        "paralyzed", "unconscious", "dead", "petrified", "restrained",
    ])
    def test_blocking_conditions(self, condition: str):
        ch = Character(
            id="hero", name="Hero", type="pc", location_id="town",
            conditions=[condition],
        )
        assert is_eligible(ch) is False

    def test_mixed_conditions_still_blocking(self):
        ch = Character(
            id="hero", name="Hero", type="pc", location_id="town",
            conditions=["panicked", "paralyzed"],  # panicked is non-blocking, paralyzed is blocking
        )
        assert is_eligible(ch) is False


class TestFilterEligible:
    def test_filters_out_blocking_conditions(self):
        eligible = Character(id="hero", name="Hero", type="pc", location_id="town")
        blocked = Character(
            id="statue", name="Statue", type="npc", location_id="town",
            conditions=["petrified"],
        )
        result = filter_eligible([eligible, blocked])
        assert len(result) == 1
        assert result[0].id == "hero"

    def test_empty_list(self):
        assert filter_eligible([]) == []
