"""Pipeline-specific exceptions."""

from __future__ import annotations


class PipelineError(RuntimeError):
    """Base exception for a pipeline stage failure."""


class AuthError(PipelineError):
    """The owner's signed-in browser session is no longer valid."""


class LimitError(PipelineError):
    """A platform or provider limit stopped the stage (credits, daily cap)."""


class PlanRequired(PipelineError):
    """Everygen requires an active plan or credit top-up before generating."""


class PublishError(PipelineError):
    """A platform publish failed."""


class GuestUnavailable(PipelineError):
    """The Cua VM or its browser environment is unavailable."""
