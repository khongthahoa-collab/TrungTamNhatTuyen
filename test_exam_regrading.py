"""Focused tests for refreshing submitted exam grades after answer-key changes."""
import json
import unittest
from types import SimpleNamespace

from blueprints.exams_shared import (
    attempt_result_is_stale,
    has_stale_scoring,
    regrade_attempt_if_stale,
)


class Attempt:
    status = 'submitted'
    order_data = {'groups': [{'q_order': [0], 'opt_orders': {'0': [0, 1]}}]}
    answers = {'g0_q1': '1'}
    score = 0
    result_json = json.dumps({
        'earned': 0.0,
        'total': 1.0,
        'percent': 0,
        'score_10': 0.0,
        'scoring_mode': 'question',
        'breakdown': [{'title': 'Phần 1', 'type': 'mcq', 'earned': 0.0, 'total': 1.0}],
    })

    @property
    def result(self):
        return json.loads(self.result_json)


class AttemptCollection:
    def __init__(self, attempts):
        self.items = attempts

    def filter_by(self, **kwargs):
        return self

    def all(self):
        return self.items


class SubmittedAttemptRegradingTests(unittest.TestCase):
    def test_stale_grade_is_refreshed_from_current_answer_key(self):
        attempt = Attempt()
        exam = SimpleNamespace(
            question_groups=[{
                'title': 'Phần 1',
                'type': 'mcq',
                'questions': [{
                    'text': 'Câu hỏi',
                    'options': ['A', 'B'],
                    'correct_index': 0,
                }],
            }],
            scoring_mode='question',
            scoring_config={},
            attempts=AttemptCollection([attempt]),
        )

        self.assertTrue(attempt_result_is_stale(exam, attempt))
        self.assertTrue(has_stale_scoring(exam, 'question'))
        self.assertTrue(regrade_attempt_if_stale(exam, attempt))
        self.assertEqual(attempt.result['score_10'], 10.0)
        self.assertEqual(attempt.score, 100)
        self.assertFalse(attempt_result_is_stale(exam, attempt))
        self.assertFalse(regrade_attempt_if_stale(exam, attempt))

        attempt.score = 0
        self.assertTrue(attempt_result_is_stale(exam, attempt))
        self.assertTrue(regrade_attempt_if_stale(exam, attempt))
        self.assertEqual(attempt.score, 100)


if __name__ == '__main__':
    unittest.main()
