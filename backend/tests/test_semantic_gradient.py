"""
Unit tests for SemanticGradient.
"""
import pytest
from backend.semantic_gradient import SemanticGradient


class TestSemanticGradient:
    """Test semantic gradient transitions."""

    def test_initialization(self):
        g = SemanticGradient(["a", "b", "c", "d"], current="b")
        assert g.current == "b"
        assert g.current_index == 1

    def test_shift_up(self):
        g = SemanticGradient(["fresh", "slight_breath", "muscle_ache", "exhausted"], current="fresh")
        assert g.shift(+1) is True
        assert g.current == "slight_breath"

    def test_shift_down(self):
        g = SemanticGradient(["fresh", "slight_breath", "muscle_ache", "exhausted"], current="muscle_ache")
        assert g.shift(-1) is True
        assert g.current == "slight_breath"

    def test_prevent_skipping(self):
        g = SemanticGradient(["fresh", "slight_breath", "muscle_ache", "exhausted"], current="fresh")
        # Try to skip from fresh to muscle_ache (+2)
        assert g.shift(+2) is False
        assert g.current == "fresh"

    def test_safe_environment_bonus(self):
        g = SemanticGradient(["fresh", "slight_breath", "muscle_ache", "exhausted"], current="muscle_ache")
        # In safe environment, can shift -2
        assert g.shift(-2, environment="safe") is True
        assert g.current == "fresh"

    def test_collapse_irreversible(self):
        g = SemanticGradient(["fresh", "slight_breath", "muscle_ache", "exhausted", "collapse"], current="collapse")
        # Cannot recover from collapse
        assert g.shift(-1) is False
        assert g.current == "collapse"

    def test_out_of_bounds(self):
        g = SemanticGradient(["a", "b", "c"], current="a")
        # Cannot go below index 0
        assert g.shift(-1) is False
        assert g.current == "a"

        # Cannot go beyond last index
        g2 = SemanticGradient(["a", "b", "c"], current="c")
        assert g2.shift(+1) is False
        assert g2.current == "c"
