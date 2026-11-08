"""Shared domain errors.

These errors are translated to explicit HTTP responses in ``app.main``.
"""


class FactoryError(Exception):
    """Base class for expected, user-actionable failures."""


class NotFound(FactoryError):
    pass


class Conflict(FactoryError):
    pass


class ValidationProblem(FactoryError):
    pass


class ApprovalRequired(FactoryError):
    """A founder approval record is missing or not approved."""


class PolicyError(FactoryError):
    """An action is blocked by company policy or a disabled integration."""


class RightsError(PermissionError):
    """Media does not have valid, approved commercial rights."""


class MediaToolUnavailable(PolicyError):
    """A required local media tool is not installed."""
