"""Tests for the ALL_CAPS feature generation in clean_for_classical.

The ALL_CAPS feature token is appended after each uppercase alphabetic
word (len >= 2) so that emphasis signals are preserved at the feature
space level for the XGBoost/TF-IDF pipeline.

Regression test: previously, text.lower() was called BEFORE _tag_all_caps,
so the ALL_CAPS feature was never generated. The fix moves lowercasing
to after _tag_all_caps so uppercase words can be detected.
"""
from app.services.preprocessing import clean_for_classical


def test_all_caps_feature_generated():
    """Uppercase words (len >= 2) should trigger ALL_CAPS feature tokens."""
    result = clean_for_classical("This is a GREAT school")
    assert "all_caps" in result
    assert "great" in result


def test_all_caps_multiple_words():
    """Multiple uppercase words should each get an ALL_CAPS tag."""
    result = clean_for_classical("The teachers are TERRIBLE but the facilities are GOOD")
    # Count occurrences of all_caps
    tokens = result.split()
    assert tokens.count("all_caps") == 2
    assert "terrible" in result
    assert "good" in result


def test_no_all_caps_for_lowercase():
    """Lowercase text should not generate ALL_CAPS features."""
    result = clean_for_classical("this is a normal comment")
    assert "all_caps" not in result


def test_all_caps_min_length():
    """Single-character uppercase words should NOT trigger ALL_CAPS (len < 2)."""
    result = clean_for_classical("I am a student")
    # "I" is uppercase but len < 2, so no ALL_CAPS
    assert "all_caps" not in result


def test_all_caps_two_char_word():
    """Two-character uppercase words should trigger ALL_CAPS (len >= 2)."""
    result = clean_for_classical("IT is ok")
    assert "all_caps" in result
    assert "it" in result


def test_all_caps_preserves_other_features():
    """ALL_CAPS should work alongside other preprocessing features."""
    result = clean_for_classical("I give 10/10 for this AMAZING experience")
    assert "all_caps" in result
    assert "amazing" in result
    assert "num" in result


def test_all_caps_with_punctuation():
    """ALL_CAPS should work even when words are followed by punctuation."""
    result = clean_for_classical("The school is GREAT!")
    assert "all_caps" in result
    assert "great" in result


def test_empty_string():
    """Empty string should return empty string."""
    assert clean_for_classical("") == ""


def test_all_caps_only():
    """A string of only uppercase words should tag each one."""
    result = clean_for_classical("GREAT SCHOOL")
    tokens = result.split()
    # Should have: great, all_caps, school, all_caps
    assert tokens.count("all_caps") == 2
    assert "great" in result
    assert "school" in result
