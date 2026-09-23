"""File-level checks. The format is decided by the file's content, never by its extension."""
import hashlib
import io
import zipfile
from pathlib import Path


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def detect_format(data):
    if data[:5] == b"%PDF-":
        return "pdf"
    if data[:2] == b"PK":
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                if "word/document.xml" in z.namelist():
                    return "docx"
        except zipfile.BadZipFile:
            return None
    return None


def check_file(data, filename, max_mb, allowed_formats):
    """Return (format, errors, warnings)."""
    errors, warnings = [], []
    if not data:
        return None, ["The file is empty."], warnings
    size_mb = len(data) / (1024 * 1024)
    if size_mb > max_mb:
        errors.append(f"The file is {size_mb:.1f} MB; the limit is {max_mb} MB.")
    fmt = detect_format(data)
    if fmt is None or fmt not in allowed_formats:
        errors.append("Unsupported file type. Upload a PDF or Word (.docx) document.")
        return None, errors, warnings
    extension = Path(filename or "").suffix.lower().lstrip(".")
    if extension and extension != fmt:
        warnings.append(f"The file is named .{extension} but its content is {fmt.upper()}; it was read as {fmt.upper()}.")
    return fmt, errors, warnings
