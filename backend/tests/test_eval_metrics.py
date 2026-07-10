"""Tests for the programmatic eval metrics (app.eval.metrics)."""

import datetime

from app.eval.metrics import (
    honesty_on_no_cause,
    numeric_consistency,
    retrieval_recall,
    trend_start_accuracy,
)


class TestRetrievalRecall:
    def test_true_when_a_chunk_source_url_contains_the_expected_ref(self):
        grounding_set = {"filing:1": {"source_url": "https://www.sec.gov/Archives/edgar/data/320193/000032019324000006/doc.htm"}}
        assert retrieval_recall("000032019324000006", grounding_set) is True

    def test_false_when_no_chunk_matches(self):
        grounding_set = {"filing:1": {"source_url": "https://www.sec.gov/Archives/edgar/data/320193/999/doc.htm"}}
        assert retrieval_recall("000032019324000006", grounding_set) is False

    def test_false_for_empty_grounding_set(self):
        assert retrieval_recall("anything", {}) is False


class TestNumericConsistency:
    def test_true_when_cited_number_matches_within_tolerance(self):
        assert numeric_consistency("Revenue was $119.6 billion this quarter.", [119575000000.0]) is True

    def test_false_when_cited_number_is_far_off(self):
        assert numeric_consistency("Revenue was $50 billion this quarter.", [119575000000.0]) is False

    def test_true_when_no_numbers_are_cited(self):
        assert numeric_consistency("The company announced a new partnership.", [119575000000.0]) is True

    def test_million_suffix_is_scaled_correctly(self):
        assert numeric_consistency("Capex was $2.4 million.", [2392000.0]) is True


class TestTrendStartAccuracy:
    def test_true_when_within_range(self):
        assert trend_start_accuracy(
            datetime.date(2024, 3, 15), datetime.date(2024, 3, 1), datetime.date(2024, 3, 31)
        ) is True

    def test_false_when_before_range(self):
        assert trend_start_accuracy(
            datetime.date(2024, 2, 15), datetime.date(2024, 3, 1), datetime.date(2024, 3, 31)
        ) is False

    def test_false_when_after_range(self):
        assert trend_start_accuracy(
            datetime.date(2024, 4, 15), datetime.date(2024, 3, 1), datetime.date(2024, 3, 31)
        ) is False


class TestHonestyOnNoCause:
    def test_true_when_expected_no_cause_and_agent_agrees(self):
        assert honesty_on_no_cause("no_clear_cause", True) is True

    def test_false_when_expected_no_cause_but_agent_fabricates_one(self):
        assert honesty_on_no_cause("no_clear_cause", False) is False

    def test_false_when_a_real_cause_exists_but_agent_gives_up(self):
        assert honesty_on_no_cause("litigation", True) is False

    def test_true_when_a_real_cause_exists_and_agent_finds_it(self):
        assert honesty_on_no_cause("litigation", False) is True
