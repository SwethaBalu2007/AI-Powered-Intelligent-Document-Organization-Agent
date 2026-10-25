"""
Document text extraction module.
Safely extracts plain text from PDF, DOCX, XLSX, and TXT files.
Operates strictly in read-only mode.
Treats all document content as untrusted plain data, never as code or instructions.
"""

import os
import re
from typing import Dict, Any, Optional

try:
    from pypdf import PdfReader
except ImportError:
    PdfReader = None

try:
    import docx
except ImportError:
    docx = None

try:
    import openpyxl
except ImportError:
    openpyxl = None


def sanitize_text(text: str) -> str:
    """Sanitizes text by removing non-printable/control characters and excess whitespace."""
    if not text:
        return ""
    # Strip null bytes and non-printable control chars (except newline and tab)
    cleaned = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', ' ', text)
    # Collapse consecutive spaces
    cleaned = re.sub(r'[ \t]+', ' ', cleaned)
    return cleaned.strip()


def extract_text_from_pdf(file_path: str, max_pages: int = 15) -> Dict[str, Any]:
    """Safely extracts text and metadata from a PDF file using pypdf."""
    if PdfReader is None:
        return {"text": "", "error": "pypdf library not available"}
    try:
        reader = PdfReader(file_path)
        extracted_pages = []
        num_pages = len(reader.pages)
        for i in range(min(num_pages, max_pages)):
            page_text = reader.pages[i].extract_text() or ""
            extracted_pages.append(page_text)
        
        full_text = "\n".join(extracted_pages)
        return {
            "text": sanitize_text(full_text),
            "pages": num_pages,
            "error": None
        }
    except Exception as e:
        return {"text": "", "pages": 0, "error": f"PDF parse error: {str(e)}"}


def extract_text_from_docx(file_path: str) -> Dict[str, Any]:
    """Safely extracts text from a DOCX file without executing macros."""
    if docx is None:
        return {"text": "", "error": "python-docx library not available"}
    try:
        doc = docx.Document(file_path)
        paragraphs = [p.text for p in doc.paragraphs if p.text]
        # Also extract table text
        table_texts = []
        for table in doc.tables:
            for row in table.rows:
                row_text = " | ".join(cell.text.strip() for cell in row.cells if cell.text.strip())
                if row_text:
                    table_texts.append(row_text)
        
        full_text = "\n".join(paragraphs + table_texts)
        return {
            "text": sanitize_text(full_text),
            "paragraphs": len(paragraphs),
            "error": None
        }
    except Exception as e:
        return {"text": "", "paragraphs": 0, "error": f"DOCX parse error: {str(e)}"}


def extract_text_from_xlsx(file_path: str, max_rows: int = 100) -> Dict[str, Any]:
    """Safely extracts tabular data summary from an Excel spreadsheet."""
    if openpyxl is None:
        return {"text": "", "error": "openpyxl library not available"}
    try:
        wb = openpyxl.load_workbook(file_path, read_only=True, data_only=True)
        sheets_data = []
        for sheetname in wb.sheetnames[:5]:
            sheet = wb[sheetname]
            sheets_data.append(f"Sheet: {sheetname}")
            row_count = 0
            for row in sheet.iter_rows(values_only=True):
                if row_count >= max_rows:
                    break
                row_str = " | ".join(str(cell) for cell in row if cell is not None)
                if row_str.strip():
                    sheets_data.append(row_str)
                    row_count += 1
        wb.close()
        full_text = "\n".join(sheets_data)
        return {
            "text": sanitize_text(full_text),
            "error": None
        }
    except Exception as e:
        return {"text": "", "error": f"XLSX parse error: {str(e)}"}


def extract_text_from_txt(file_path: str, max_bytes: int = 500_000) -> Dict[str, Any]:
    """Extracts text from plain text or markdown/csv files safely."""
    encodings = ["utf-8", "latin-1", "cp1252"]
    for enc in encodings:
        try:
            with open(file_path, "r", encoding=enc, errors="replace") as f:
                content = f.read(max_bytes)
                return {
                    "text": sanitize_text(content),
                    "error": None
                }
        except Exception:
            continue
    return {"text": "", "error": "Unable to decode text file"}


def extract_document_content(file_path: str) -> Dict[str, Any]:
    """
    Main extraction router based on file extension.
    Returns dictionary with extracted text, extension, size, and error status.
    """
    if not os.path.exists(file_path):
        return {"text": "", "error": "File does not exist", "supported": False}
    
    ext = os.path.splitext(file_path)[1].lower()
    file_size = os.path.getsize(file_path)

    supported = True
    result: Dict[str, Any] = {"text": "", "error": None}

    if ext == ".pdf":
        result = extract_text_from_pdf(file_path)
    elif ext in [".docx", ".doc"]:
        result = extract_text_from_docx(file_path)
    elif ext in [".xlsx", ".xls"]:
        result = extract_text_from_xlsx(file_path)
    elif ext in [".txt", ".md", ".csv", ".json", ".log"]:
        result = extract_text_from_txt(file_path)
    else:
        supported = False
        result = {"text": "", "error": f"Unsupported file type: {ext}"}

    return {
        "file_name": os.path.basename(file_path),
        "file_path": file_path,
        "extension": ext,
        "size_bytes": file_size,
        "supported": supported,
        "text": result.get("text", ""),
        "error": result.get("error")
    }
