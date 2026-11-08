"""Tests for reaction score calculation."""

import pytest

from aetherdm.models import Character
from aetherdm.simulation.reaction import calculate_reaction_score, order_characters_by_reaction


class TestReactionScore:
    def test_base_score_equals_quickness(self):
        ch = Character(id="hero", name="Hero", type="pc", location_id="town", quickness=5)
        assert calculate_reaction_score(ch) == 5.0

    def test_panicked_penalty(self):
        ch = Character(
            id="hero",
            name="Hero",
            type="pc",
            location_id="town",
            quickness=10,
            conditions=["panicked"],
        )
        # 10 * 0.6 = 6.0
        assert calculate_reaction_score(ch) == pytest.approx(6.0)

    def test_multiple_conditions_stack(self):
        ch = Character(
            id="hero",
            name="Hero",
            type="pc",
            location_id="town",
            quickness=10,
            conditions=["panicked", "alarmed"],
        )
        # 10 * 0.6 * 0.8 = 4.8
        assert calculate_reaction_score(ch) == pytest.approx(4.8)

    def test_paralyzed_is_zero(self):
        ch = Character(
            id="hero",
            name="Hero",
            type="pc",
            location_id="town",
            quickness=10,
            conditions=["paralyzed"],
        )
        assert calculate_reaction_score(ch) == 0.0

    def test_unknown_condition_has_no_penalty(self):
        ch = Character(
            id="hero",
            name="Hero",
            type="pc",
            location_id="town",
            quickness=7,
            conditions=["confused"],  # not in penalty map
        )
        assert calculate_reaction_score(ch) == 7.0


class TestOrderCharactersByReaction:
    def test_order_by_score_descending(self):
        fast = Character(id="fast", name="Fast", type="pc", location_id="town", quickness=9)
        medium = Character(id="med", name="Medium", type="pc", location_id="town", quickness=5)
        slow = Character(id="slow", name="Slow", type="pc", location_id="town", quickness=2)

        ordered = order_characters_by_reaction([slow, medium, fast])
        assert [ch.id for ch in ordered] == ["fast", "med", "slow"]

    def test_penalties_affect_order(self):
        fast_panicked = Character(
            id="fast_panicked", name="FP", type="pc", location_id="town",
            quickness=10, conditions=["panicked"],  # 10 * 0.6 = 6.0
        )
        slow_calm = Character(
            id="slow_calm", name="SC", type="pc", location_id="town",
            quickness=7, conditions=[],  # 7.0
        )

        ordered = order_characters_by_reaction([fast_panicked, slow_calm])
        # slow_calm (7.0) > fast_panicked (6.0)
        assert [ch.id for ch in ordered] == ["slow_calm", "fast_panicked"]
