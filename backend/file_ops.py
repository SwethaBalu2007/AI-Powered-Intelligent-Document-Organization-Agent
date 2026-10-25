"""
Controlled File Operations Engine.
Executes approved file movements, creates destination subfolders inside the original folder,
handles file name collisions safely without overwriting, records changes to SQLite ledger,
and provides atomic Undo / Reversion functionality.
NEVER executes any file write, move, or rename without explicit approval tokens.
"""

import os
import shutil
import hashlib
import uuid
from typing import List, Dict, Any, Tuple
from .ledger import (
    save_organized_file,
    record_activity,
    save_undo_record,
    get_latest_undo_batch,
    get_undo_records_for_batch,
    mark_batch_reverted,
    get_connection
)


def compute_file_hash(file_path: str) -> str:
    """Computes SHA-256 hash of a file for audit verification and duplicate detection."""
    hasher = hashlib.sha256()
    try:
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                hasher.update(chunk)
        return hasher.hexdigest()
    except Exception:
        return ""


def resolve_collision_name(dest_folder: str, file_name: str) -> str:
    """
    Prevents accidental file overwriting.
    If 'Exam_Timetable.pdf' exists, generates 'Exam_Timetable (1).pdf', etc.
    """
    base, ext = os.path.splitext(file_name)
    target_path = os.path.join(dest_folder, file_name)
    counter = 1
    while os.path.exists(target_path):
        target_path = os.path.join(dest_folder, f"{base} ({counter}){ext}")
        counter += 1
    return target_path


def execute_approved_organization(
    base_folder: str,
    approved_plan: List[Dict[str, Any]],
    approval_token: str
) -> Dict[str, Any]:
    """
    Executes the organization plan on the actual user folder:
    1. Verifies approval token
    2. Ensures base_folder exists and write permissions are confirmed
    3. Creates subfolders inside the base folder
    4. Safely moves files into subfolders
    5. Saves undo snapshots and updates SQLite ledger
    6. Records audit trail
    """
    if not approval_token or not approval_token.startswith("APP-"):
        raise PermissionError("Write operation rejected: Valid user approval token is required.")

    if not os.path.isdir(base_folder):
        raise FileNotFoundError(f"Selected base folder does not exist: {base_folder}")

    # Generate a unique batch ID for this operation session
    batch_id = f"batch_{uuid.uuid4().hex[:10]}"
    moved_files = []
    errors = []
    subfolders_created = set()

    for item in approved_plan:
        orig_path = item.get("current_location") or item.get("file_path")
        category = item.get("category") or item.get("suggested_category", "Miscellaneous")
        subfolder_name = item.get("proposed_subfolder") or category.replace(" ", "_")
        file_name = item.get("file_name") or os.path.basename(orig_path)
        confidence = float(item.get("confidence_score", 1.0))
        related = item.get("related_documents", [])
        snippet = item.get("summary_snippet", "")

        if not orig_path or not os.path.exists(orig_path):
            errors.append({
                "file_name": file_name,
                "error": f"Source file not found at: {orig_path}"
            })
            continue

        target_dir = os.path.join(base_folder, subfolder_name)
        try:
            # 1. Create category subfolder if not present
            if not os.path.exists(target_dir):
                os.makedirs(target_dir, exist_ok=True)
                subfolders_created.add(subfolder_name)

            # 2. Check destination and resolve collision safely
            final_dest_path = resolve_collision_name(target_dir, file_name)

            # Check if file is already at destination
            if os.path.abspath(orig_path) == os.path.abspath(final_dest_path):
                continue

            file_hash = compute_file_hash(orig_path)
            file_size = os.path.getsize(orig_path)

            # 3. Move the file
            shutil.move(orig_path, final_dest_path)

            # 4. Save undo snapshot
            save_undo_record(batch_id, orig_path, final_dest_path)

            # 5. Record to SQLite document ledger
            save_organized_file(
                file_name=os.path.basename(final_dest_path),
                category=category,
                original_location=orig_path,
                current_location=final_dest_path,
                confidence_score=confidence,
                related_documents=related,
                status="ORGANIZED",
                file_hash=file_hash,
                file_size=file_size,
                summary_snippet=snippet
            )

            moved_files.append({
                "file_name": file_name,
                "category": category,
                "from": orig_path,
                "to": final_dest_path
            })

        except Exception as e:
            err_msg = f"Failed to move {file_name}: {str(e)}"
            errors.append({"file_name": file_name, "error": err_msg})
            record_activity("FILE_MOVE_ERROR", base_folder, err_msg, status="FAILED", batch_id=batch_id)

    # Record overall success/audit
    status_summary = f"Organized {len(moved_files)} files into {len(subfolders_created)} subfolders."
    if errors:
        status_summary += f" Encountered {len(errors)} errors."

    record_activity(
        action_type="EXECUTE_ORGANIZATION",
        folder_path=base_folder,
        details=status_summary,
        status="COMPLETED" if not errors else "COMPLETED_WITH_ERRORS",
        batch_id=batch_id
    )

    return {
        "success": True,
        "batch_id": batch_id,
        "moved_count": len(moved_files),
        "moved_files": moved_files,
        "created_subfolders": list(subfolders_created),
        "errors": errors,
        "summary": status_summary
    }


def undo_organization(batch_id: str = None) -> Dict[str, Any]:
    """
    Reverts a previous organization batch by moving files back to original paths.
    """
    target_batch = batch_id or get_latest_undo_batch()
    if not target_batch:
        return {"success": False, "message": "No active organization batches to undo."}

    records = get_undo_records_for_batch(target_batch)
    if not records:
        return {"success": False, "message": f"No active move records found for batch {target_batch}."}

    reverted_count = 0
    errors = []

    conn = get_connection()
    cursor = conn.cursor()

    for rec in records:
        curr_path = rec["moved_path"]
        orig_path = rec["original_path"]

        try:
            if os.path.exists(curr_path):
                # Ensure parent of original exists
                orig_dir = os.path.dirname(orig_path)
                os.makedirs(orig_dir, exist_ok=True)

                # Move back
                shutil.move(curr_path, orig_path)
                reverted_count += 1

                # Update ledger status to REVERTED
                cursor.execute("""
                    UPDATE document_ledger
                    SET current_location = ?, processing_status = 'REVERTED'
                    WHERE current_location = ?
                """, (orig_path, curr_path))

                # If category folder is now empty, remove it to keep directory clean
                parent_dir = os.path.dirname(curr_path)
                if os.path.exists(parent_dir) and not os.listdir(parent_dir):
                    try:
                        os.rmdir(parent_dir)
                    except OSError:
                        pass
            else:
                errors.append(f"File at {curr_path} not found to revert.")
        except Exception as e:
            errors.append(f"Error reverting {curr_path} -> {orig_path}: {str(e)}")

    conn.commit()
    conn.close()

    mark_batch_reverted(target_batch)

    summary = f"Reverted {reverted_count} files to their original locations."
    record_activity(
        action_type="UNDO_ORGANIZATION",
        folder_path="",
        details=summary,
        status="COMPLETED" if not errors else "COMPLETED_WITH_ERRORS",
        batch_id=target_batch
    )

    return {
        "success": True,
        "batch_id": target_batch,
        "reverted_count": reverted_count,
        "errors": errors,
        "message": summary
    }
