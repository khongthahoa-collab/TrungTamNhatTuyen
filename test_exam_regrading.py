"""Focused tests for refreshing submitted exam grades after answer-key changes."""
import json
import unittest
from types import SimpleNamespace

from blueprints.exams_shared import (
    attempt_result_is_stale,
    edited_question_from_form,
    has_stale_scoring,
    regrade_attempt_if_stale,
)
from werkzeug.datastructures import MultiDict


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

    def test_per_question_editor_updates_mcq_key_without_changing_shape(self):
        question = {
            'text': 'Old question',
            'options': ['Old A', 'Old B'],
            'correct_index': 1,
            'explanation': '',
        }
        form = MultiDict([
            ('text', 'Updated question'),
            ('explanation', 'Because of this.'),
            ('option_0', 'New A'),
            ('option_1', 'New B'),
            ('correct_index', '0'),
        ])

        updated, error = edited_question_from_form('mcq', question, form)

        self.assertIsNone(error)
        self.assertEqual(updated['text'], 'Updated question')
        self.assertEqual(updated['options'], ['New A', 'New B'])
        self.assertEqual(updated['correct_index'], 0)
        self.assertEqual(len(updated['options']), len(question['options']))

    def test_per_question_editor_updates_true_false_and_short_answers(self):
        tf_question = {
            'text': 'Old statement group',
            'statements': [{'text': 'Old a', 'correct': False}, {'text': 'Old b', 'correct': True}],
        }
        tf_form = MultiDict([
            ('text', 'Updated group'),
            ('statement_0', 'Updated a'),
            ('statement_correct_0', '1'),
            ('statement_1', 'Updated b'),
            ('statement_correct_1', '0'),
        ])
        updated_tf, tf_error = edited_question_from_form('true_false', tf_question, tf_form)
        self.assertIsNone(tf_error)
        self.assertEqual(
            updated_tf['statements'],
            [{'text': 'Updated a', 'correct': True}, {'text': 'Updated b', 'correct': False}],
        )

        short_question = {'text': 'Old question', 'accepted_answers': ['one']}
        short_form = MultiDict([
            ('text', 'Updated question'),
            ('accepted_answers', 'first answer\nsecond answer'),
        ])
        updated_short, short_error = edited_question_from_form('short_answer', short_question, short_form)
        self.assertIsNone(short_error)
        self.assertEqual(updated_short['accepted_answers'], ['first answer', 'second answer'])

    def test_per_question_editor_rejects_invalid_answer_key(self):
        question = {
            'text': 'Question',
            'options': ['A', 'B'],
            'correct_index': 0,
            'explanation': '',
        }
        form = MultiDict([
            ('text', 'Question'),
            ('option_0', 'A'),
            ('option_1', 'B'),
            ('correct_index', '5'),
        ])

        updated, error = edited_question_from_form('mcq', question, form)

        self.assertIsNone(updated)
        self.assertIsNotNone(error)


if __name__ == '__main__':
    unittest.main()
