"""
Local Searchable Document Ledger and Activity Audit Log.
Utilizes SQLite to store document history, classification confidence,
related document references, file locations, and atomic undo snapshots.
"""

import os
import sqlite3
import json
from datetime import datetime
from typing import List, Dict, Any, Optional

DB_FILE = os.path.join(os.path.dirname(__file__), "document_ledger.db")


def get_connection() -> sqlite3.Connection:
    """Creates connection and enables dictionary-like row access."""
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Initializes schema for document ledger and activity audit logs."""
    conn = get_connection()
    cursor = conn.cursor()

    # Documents Ledger Table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS document_ledger (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            file_name TEXT NOT NULL,
            category TEXT NOT NULL,
            original_location TEXT NOT NULL,
            current_location TEXT NOT NULL,
            processing_status TEXT NOT NULL,
            processed_at TEXT NOT NULL,
            confidence_score REAL NOT NULL,
            related_documents TEXT, -- JSON array of related items
            file_hash TEXT,
            file_size INTEGER,
            summary_snippet TEXT
        )
    """)

    # Activity and Audit Log Table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS activity_audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            action_type TEXT NOT NULL,
            folder_path TEXT NOT NULL,
            details TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            batch_id TEXT,
            status TEXT NOT NULL
        )
    """)

    # Undo Stack Table (Records file moves per batch for 1-click rollback)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS undo_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            batch_id TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            original_path TEXT NOT NULL,
            moved_path TEXT NOT NULL,
            status TEXT NOT NULL -- 'ACTIVE' or 'REVERTED'
        )
    """)

    conn.commit()
    conn.close()


def record_activity(action_type: str, folder_path: str, details: str, status: str = "SUCCESS", batch_id: str = None) -> int:
    """Logs an agent activity or error into the audit table."""
    conn = get_connection()
    cursor = conn.cursor()
    now_str = datetime.now().isoformat()
    cursor.execute("""
        INSERT INTO activity_audit_log (action_type, folder_path, details, timestamp, batch_id, status)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (action_type, folder_path, details, now_str, batch_id, status))
    log_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return log_id


def save_organized_file(
    file_name: str,
    category: str,
    original_location: str,
    current_location: str,
    confidence_score: float,
    related_documents: List[Dict[str, Any]],
    status: str = "ORGANIZED",
    file_hash: str = "",
    file_size: int = 0,
    summary_snippet: str = ""
) -> int:
    """Records or updates a document in the searchable ledger."""
    conn = get_connection()
    cursor = conn.cursor()
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Check if this file already exists in ledger by original_location
    cursor.execute("SELECT id FROM document_ledger WHERE original_location = ? OR current_location = ?", 
                   (original_location, current_location))
    existing = cursor.fetchone()

    rel_json = json.dumps(related_documents)

    if existing:
        cursor.execute("""
            UPDATE document_ledger
            SET file_name = ?, category = ?, current_location = ?, processing_status = ?,
                processed_at = ?, confidence_score = ?, related_documents = ?,
                file_hash = ?, file_size = ?, summary_snippet = ?
            WHERE id = ?
        """, (file_name, category, current_location, status, now_str, confidence_score,
              rel_json, file_hash, file_size, summary_snippet, existing["id"]))
        doc_id = existing["id"]
    else:
        cursor.execute("""
            INSERT INTO document_ledger (
                file_name, category, original_location, current_location,
                processing_status, processed_at, confidence_score,
                related_documents, file_hash, file_size, summary_snippet
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (file_name, category, original_location, current_location, status,
              now_str, confidence_score, rel_json, file_hash, file_size, summary_snippet))
        doc_id = cursor.lastrowid

    conn.commit()
    conn.close()
    return doc_id


def search_ledger(
    query: str = "",
    category: str = "",
    status: str = "",
    limit: int = 100
) -> List[Dict[str, Any]]:
    """
    Searches the SQLite ledger by file name, keywords in snippet, category, or status.
    """
    conn = get_connection()
    cursor = conn.cursor()

    sql = "SELECT * FROM document_ledger WHERE 1=1"
    params = []

    if query.strip():
        sql += " AND (file_name LIKE ? OR summary_snippet LIKE ? OR original_location LIKE ?)"
        wildcard = f"%{query.strip()}%"
        params.extend([wildcard, wildcard, wildcard])

    if category.strip() and category != "All":
        sql += " AND category = ?"
        params.append(category.strip())

    if status.strip() and status != "All":
        sql += " AND processing_status = ?"
        params.append(status.strip())

    sql += " ORDER BY id DESC LIMIT ?"
    params.append(limit)

    cursor.execute(sql, params)
    rows = cursor.fetchall()

    results = []
    for r in rows:
        d = dict(r)
        try:
            d["related_documents"] = json.loads(d["related_documents"]) if d["related_documents"] else []
        except Exception:
            d["related_documents"] = []
        results.append(d)

    conn.close()
    return results


def get_audit_logs(limit: int = 50) -> List[Dict[str, Any]]:
    """Retrieves recent audit activities."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM activity_audit_log ORDER BY id DESC LIMIT ?", (limit,))
    rows = cursor.fetchall()
    logs = [dict(r) for r in rows]
    conn.close()
    return logs


def save_undo_record(batch_id: str, original_path: str, moved_path: str):
    """Saves a move entry for rollback capabilities."""
    conn = get_connection()
    cursor = conn.cursor()
    now_str = datetime.now().isoformat()
    cursor.execute("""
        INSERT INTO undo_snapshots (batch_id, timestamp, original_path, moved_path, status)
        VALUES (?, ?, ?, ?, 'ACTIVE')
    """, (batch_id, now_str, original_path, moved_path))
    conn.commit()
    conn.close()


def get_latest_undo_batch() -> Optional[str]:
    """Finds the most recent active batch ID that can be undone."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT batch_id FROM undo_snapshots WHERE status = 'ACTIVE' ORDER BY id DESC LIMIT 1")
    row = cursor.fetchone()
    conn.close()
    return row["batch_id"] if row else None


def get_undo_records_for_batch(batch_id: str) -> List[Dict[str, Any]]:
    """Fetches all move records for a batch."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM undo_snapshots WHERE batch_id = ? AND status = 'ACTIVE'", (batch_id,))
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return rows


def mark_batch_reverted(batch_id: str):
    """Marks batch as reverted in undo records and updates ledger status."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE undo_snapshots SET status = 'REVERTED' WHERE batch_id = ?", (batch_id,))
    conn.commit()
    conn.close()


# Initialize database upon import
init_db()
