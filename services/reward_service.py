"""
Reward Service - automatically suggest rewards based on scores.
Primary: no auto-suggestion (admin decides manually).
Secondary/HighSchool: follows rules defined in business logic.
"""
from models import Reward, StudentLevel, ScoreType


# Reward rules for Secondary/HighSchool
# (score_type_group, min_score): amount (VND)
REWARD_RULES = {
    ('continuous_assessment', 9): 20_000,
    ('continuous_assessment', 10): 50_000,
    ('periodic_exam', 8): 100_000,
    ('periodic_exam', 9): 150_000,
    ('periodic_exam', 10): 200_000,
}

# Map score types to groups
SCORE_TYPE_GROUPS = {
    ScoreType.CONTINUOUS: 'continuous_assessment',
    ScoreType.QUIZ_15: 'continuous_assessment',
    ScoreType.ORAL: 'continuous_assessment',
    ScoreType.MIDTERM: 'periodic_exam',
    ScoreType.FINAL: 'periodic_exam',
}


def suggest_reward(score):
    """
    Check if a score qualifies for a reward.
    Returns dict with 'amount' and 'reason', or None.
    """
    student = score.student
    
    # Primary students: no auto-suggestion
    if student.level == StudentLevel.PRIMARY:
        return None

    # Only Secondary and High School
    if student.level not in (StudentLevel.SECONDARY, StudentLevel.HIGH_SCHOOL):
        return None

    group = SCORE_TYPE_GROUPS.get(score.score_type)
    if not group:
        return None

    val = score.score_value
    amount = None

    if group == 'continuous_assessment':
        if val >= 10:
            amount = REWARD_RULES[('continuous_assessment', 10)]
        elif val >= 9:
            amount = REWARD_RULES[('continuous_assessment', 9)]
    elif group == 'periodic_exam':
        if val >= 10:
            amount = REWARD_RULES[('periodic_exam', 10)]
        elif val >= 9:
            amount = REWARD_RULES[('periodic_exam', 9)]
        elif val >= 8:
            amount = REWARD_RULES[('periodic_exam', 8)]

    if amount is None:
        return None

    reason = (
        f"Score {score.score_type_label} {score.score_value}/{score.max_score} "
        f"in {score.class_.course.name} ({score.class_.name})"
    )
    return {'amount': amount, 'reason': reason}


def create_suggested_reward(score, created_by_id):
    """
    Tạo bản ghi Reward đề xuất (is_confirmed=False).
    Trả về Reward object hoặc None nếu không đủ điều kiện.
    """
    from extensions import db
    from datetime import date

    suggestion = suggest_reward(score)
    if not suggestion:
        return None

    reward = Reward(
        student_id=score.student_id,
        reason=suggestion['reason'],
        amount=suggestion['amount'],
        reward_type='cash',
        reward_date=score.exam_date or date.today(),
        is_suggested=True,
        is_confirmed=False,
        score_id=score.id,
        created_by=created_by_id,
    )
    db.session.add(reward)
    score.reward_suggested = True
    db.session.commit()
    return reward
