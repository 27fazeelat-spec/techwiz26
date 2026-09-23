"""Contradiction detection and policy precedence (SRS Steps 33-34). Deterministic; no GenAI."""
from contradiction_checks.detector import detect
from contradiction_checks.precedence import resolve

__all__ = ["detect", "resolve"]
