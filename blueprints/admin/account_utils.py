"""Shared helpers for the account-creation flows (accounts page + parent
auto-create on student creation), so username/password defaults stay in sync."""
from models import User

DEFAULT_TEMP_PASSWORD = 'pass@123'
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
