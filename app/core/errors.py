"""The shared domain-error marker.

Extracted here once a second domain module (team, membership) grew its own error
variants — a cross-domain marker shouldn't live inside one domain. This is the
graduation point noted when the marker was first added to `user.py`.
"""


class DomainError:
    """Marker for expected, value-level failures: they travel on a Result's
    error track and are never raised. Deliberately NOT an `Exception` — that
    would blur the §6 line between domain errors (values) and panics (raised).
    `__slots__ = ()` so frozen, slotted subclasses keep their slots."""

    __slots__ = ()
