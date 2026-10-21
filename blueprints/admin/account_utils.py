"""Shared helpers for the account-creation flows (accounts page + parent
auto-create on student creation), so username/password defaults stay in sync."""
import re
import unicodedata

from sqlalchemy import func

from models import User

DEFAULT_TEMP_PASSWORD = 'pass@123'
DEFAULT_STUDENT_TEMP_PASSWORD = '@Abc123'
USERNAME_PREFIXES = {'admin': 'admin', 'teacher': 'teacher', 'parent': 'user', 'student': 'student'}


def next_username(role):
    """Return the first available username for the requested account role."""
    prefix = USERNAME_PREFIXES.get(role, 'user')
    n = 1
    while True:
        candidate = f'{prefix}{n}'
        if not User.query.filter_by(username=candidate).first():
            return candidate
        n += 1


def next_student_username(full_name, current_grade, taken=None):
    """Build a readable student username and append a number when it exists.
    `taken` (a set of lower-cased usernames) replaces the per-candidate DB
    lookup for bulk creation; the chosen name is added to it."""
    normalized_name = unicodedata.normalize(
        'NFKD', (full_name or '').replace('Đ', 'D').replace('đ', 'd')
    )
    ascii_name = normalized_name.encode('ascii', 'ignore').decode('ascii')
    name_parts = re.findall(r'[A-Za-z0-9]+', ascii_name)
    name = ''.join(part.capitalize() for part in name_parts) or 'Student'

    grade_match = re.search(r'\d+', current_grade or '')
    base = f'{name}{grade_match.group()}' if grade_match else name
    base = base[:50]
    candidate = base
    suffix = 2
    def exists(name):
        if taken is not None:
            return name.lower() in taken
        return User.query.filter(func.lower(User.username) == name.lower()).first() is not None

    while exists(candidate):
        suffix_text = str(suffix)
        candidate = f'{base[:50 - len(suffix_text)]}{suffix_text}'
        suffix += 1
    if taken is not None:
        taken.add(candidate.lower())
    return candidate
