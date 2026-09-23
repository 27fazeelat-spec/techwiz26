from document_validation import check_file, detect_format

from tests.conftest import SAMPLES


def test_detects_formats_from_content():
    assert detect_format((SAMPLES / "HBK-01_v3.0.pdf").read_bytes()) == "pdf"
    assert detect_format((SAMPLES / "HRP-01_v2.1.docx").read_bytes()) == "docx"
    assert detect_format(b"just some text") is None
    assert detect_format(b"PK\x03\x04not really a zip") is None


def test_rejects_empty_and_unsupported_files():
    assert check_file(b"", "x.pdf", 15, ["pdf", "docx"])[1] == ["The file is empty."]
    fmt, errors, _ = check_file(b"hello world", "notes.txt", 15, ["pdf", "docx"])
    assert fmt is None and "Unsupported file type" in errors[0]


def test_rejects_oversized_file():
    data = (SAMPLES / "HBK-01_v3.0.pdf").read_bytes()
    _, errors, _ = check_file(data, "big.pdf", max_mb=0.001, allowed_formats=["pdf"])
    assert any("limit" in e for e in errors)


def test_extension_mismatch_is_a_warning_not_a_rejection():
    data = (SAMPLES / "HRP-01_v2.1.docx").read_bytes()
    fmt, errors, warnings = check_file(data, "renamed.pdf", 15, ["pdf", "docx"])
    assert fmt == "docx" and not errors and "content is DOCX" in warnings[0]
