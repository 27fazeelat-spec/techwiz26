"""Entry point: pick the parser for a detected file format."""
from document_processing.docx_parser import parse_docx
from document_processing.pdf_parser import parse_pdf


def parse_document(data, fmt):
    if fmt == "pdf":
        return parse_pdf(data)
    if fmt == "docx":
        return parse_docx(data)
    raise ValueError(f"unsupported format: {fmt}")
