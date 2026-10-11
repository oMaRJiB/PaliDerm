"""Small shared validators; free text is validated without normalization."""
import re
from datetime import date, datetime, timezone


class Problem(Exception):
    """Carry a translated error key and HTTP status without embedding sensitive input."""
    def __init__(self, key, status=400):
        """Store the catalog key/status consumed by the shared HTTP error handler."""
        self.key, self.status = key, status


def now():
    """Return a UTC ISO-8601 event timestamp with microseconds."""
    return datetime.now(timezone.utc).isoformat(timespec='microseconds').replace('+00:00', 'Z')


def required(value):
    """Reject blank required text but preserve accepted Unicode and surrounding whitespace exactly."""
    if not isinstance(value, str) or not value.strip():
        raise Problem('required')
    return value


def calendar(value, birth=False):
    """Validate an optional real ISO calendar date; birth dates cannot be in the future."""
    if not value:
        return None
    try:
        if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
            raise ValueError()
        parsed = date.fromisoformat(value)
        if birth and parsed > datetime.now(timezone.utc).date():
            raise ValueError()
    except (ValueError, TypeError):
        raise Problem('invalid_date') from None
    return value


def integer(value):
    """Parse optional bounded nonnegative whole-number duration; reject malformed or oversized input."""
    if value == '' or value is None:
        return None
    if not isinstance(value, str) or not re.fullmatch(r'[0-9]+', value) or len(value) > 8:
        raise Problem('invalid_duration')
    return int(value)


def choice(value, allowed):
    """Accept only a server-declared enum value; raise a translated Problem otherwise."""
    if value not in allowed:
        raise Problem('invalid_choice')
    return value


def role(identity, expected):
    """Require a resolved identity with the expected server-owned role."""
    if not identity or identity['role'] != expected:
        raise Problem('forbidden', 403)
