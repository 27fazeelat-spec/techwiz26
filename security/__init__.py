"""Security controls that must never depend on GenAI: injection scanning and content sanitising."""
from security.injection_scanner import scan_document

__all__ = ["scan_document"]
