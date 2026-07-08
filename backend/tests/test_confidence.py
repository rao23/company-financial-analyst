"""Tests for the deterministic confidence rubric (app.agent.confidence)."""

import pytest

from app.agent.confidence import derive_confidence


def test_no_clear_cause_returns_none_not_a_low_score():
    result = derive_confidence(window_tier=180, primary_citation_source_type="news", magnitude_match="weak", no_clear_cause=True)
    assert result is None


def test_narrow_window_official_source_strong_match_is_high_confidence():
    result = derive_confidence(window_tier=14, primary_citation_source_type="filing", magnitude_match="strong", no_clear_cause=False)
    assert result == pytest.approx(1.0)  # 0.90 + 0.05 + 0.05, clamped


def test_wide_window_news_source_weak_match_is_low_confidence():
    result = derive_confidence(window_tier=180, primary_citation_source_type="news", magnitude_match="weak", no_clear_cause=False)
    assert result == pytest.approx(0.30)  # 0.50 - 0.05 - 0.15


def test_narrower_window_always_scores_at_least_as_high_as_a_wider_one():
    for source_type in ("filing", "news"):
        for magnitude_match in ("strong", "weak", "unclear"):
            score_14 = derive_confidence(14, source_type, magnitude_match, False)
            score_90 = derive_confidence(90, source_type, magnitude_match, False)
            score_180 = derive_confidence(180, source_type, magnitude_match, False)
            assert score_14 >= score_90 >= score_180


def test_confidence_is_always_within_zero_and_one():
    for tier in (14, 90, 180):
        for source_type in ("filing", "news"):
            for magnitude_match in ("strong", "weak", "unclear"):
                score = derive_confidence(tier, source_type, magnitude_match, False)
                assert 0.0 <= score <= 1.0
