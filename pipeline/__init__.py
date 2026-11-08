"""GTA 6 Shorts Factory — CUA automation pipeline.

The pipeline uses the same Cua VM as ``v2-automation`` but has its own
database, guest scripts, logs and state.  No platform API keys are used:
YouTube, TikTok and Everygen are driven through the browser sessions that the
owner keeps signed in inside the Cua VM.
"""

__all__ = ["__version__"]

__version__ = "1.0.0"
