"""Pipeline 2: deterministic validation of generated plans against the Role Requirement Matrix.

No module in this package may call a GenAI API (enforced by tests/test_architecture.py).
Rules work on plain data (ValidationContext), so each one can be tested in isolation.
"""
from python_validation.engine import ValidationContext, validate

__all__ = ["ValidationContext", "validate"]
