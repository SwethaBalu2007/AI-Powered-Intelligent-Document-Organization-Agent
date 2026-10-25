"""
Main Backend Application for AI Document Organization Agent.
Provides REST and Command APIs for:
- Native OS folder selection
- Read-only document scanning & text parsing
- AI-based classification and confidence evaluation
- In-memory preview & manual category updates
- Safety-gated human approval & atomic file organization
- Undo / Rollback engine
- Searchable SQLite document ledger & audit trail
- Natural Language Chatbot agent
- Serving Desktop Frontend UI
"""

import os
import sys
import subprocess
import uuid
import re
from typing import Dict, Any, List, Optional
from fastapi import FastAPI, HTTPException, Body, UploadFile, File
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# Internal backend modules
from .extractor import extract_document_content
from .classifier import classify_document, get_available_categories
from .related import find_related_documents
from .ledger import (
    search_ledger,
    get_audit_logs,
    record_activity,
    get_latest_undo_batch
)
from .file_ops import execute_approved_organization, undo_organization
from .dialog import open_native_folder_picker, scan_directory_tree
from .sample_generator import generate_sample_college_documents

app = FastAPI(title="AI Document Organization Agent API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# In-memory session state for active folder and classification preview
active_session: Dict[str, Any] = {
    "current_folder": None,
    "scanned_documents": [],
    "classification_preview": [],
    "related_map": {},
    "pending_token": None,
    "last_batch_id": None,
    "custom_categories": []
}


def build_proposed_tree(base_folder: str, preview_items: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Constructs the visual proposed folder tree hierarchy based on current preview."""
    root_name = os.path.basename(base_folder) or base_folder
    categories: Dict[str, List[Dict[str, Any]]] = {}

    for item in preview_items:
        cat = item.get("category") or item.get("suggested_category", "Miscellaneous")
        subfolder = item.get("proposed_subfolder") or cat.replace(" ", "_")
        if subfolder not in categories:
            categories[subfolder] = []
        categories[subfolder].append({
            "name": item["file_name"],
            "extension": os.path.splitext(item["file_name"])[1].lower(),
            "confidence": item.get("confidence_score", 1.0)
        })

    children = []
    for subfolder, files in sorted(categories.items()):
        children.append({
            "name": subfolder,
            "type": "directory",
            "file_count": len(files),
            "files": files,
            "children": []
        })

    return {
        "name": root_name,
        "path": base_folder,
        "type": "directory",
        "is_proposed": True,
        "children": children
    }


# ============================================================================
# API Endpoints
# ============================================================================

@app.get("/api/status")
def get_system_status():
    """Returns agent status, current selected folder, and categories."""
    return {
        "status": "ready",
        "current_folder": active_session["current_folder"],
        "has_preview": len(active_session["classification_preview"]) > 0,
        "document_count": len(active_session["classification_preview"]),
        "available_categories": list(set(get_available_categories() + active_session["custom_categories"])),
        "can_undo": get_latest_undo_batch() is not None
    }


@app.post("/api/folder/browse")
def browse_folder():
    """Opens native OS folder picker dialog."""
    try:
        path = open_native_folder_picker()
        if not path:
            return {"cancelled": True, "folder_path": None}
        return {"cancelled": False, "folder_path": path}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/folder/list-dirs")
def list_local_directories(payload: Dict[str, Any] = Body(default={})):
    """
    Lists real directories on local filesystem so users can visually browse
    and pick folders with their mouse directly in the UI without freezing.
    """
    raw_path = (payload.get("path") or "").strip().strip('"').strip("'")
    if not raw_path:
        raw_path = active_session.get("current_folder") or os.getcwd()

    resolved = resolve_folder_path(raw_path)
    target = resolved if resolved else os.path.normpath(raw_path)
    if not os.path.exists(target) or not os.path.isdir(target):
        target = os.getcwd()

    parent = os.path.dirname(target)
    if parent == target:
        parent = None

    directories = []
    try:
        with os.scandir(target) as entries:
            for entry in entries:
                if entry.name.startswith(('.', '$')) or entry.name in ['node_modules', '__pycache__', '.git']:
                    continue
                try:
                    if entry.is_dir(follow_symlinks=False):
                        directories.append({
                            "name": entry.name,
                            "path": entry.path
                        })
                except (PermissionError, OSError):
                    continue
    except (PermissionError, OSError) as e:
        raise HTTPException(status_code=403, detail=f"Permission denied: {str(e)}")

    directories.sort(key=lambda x: x["name"].lower())

    quick_jumps = [
        {"name": "Downloads", "path": os.path.join(os.path.expanduser("~"), "Downloads")},
        {"name": "Sample Documents", "path": os.path.join(os.getcwd(), "Sample_College_Documents")},
        {"name": "Current Workspace", "path": os.getcwd()},
        {"name": "Documents", "path": os.path.join(os.path.expanduser("~"), "Documents")},
        {"name": "User Home", "path": os.path.expanduser("~")},
    ]
    quick_jumps = [q for q in quick_jumps if os.path.exists(q["path"])]

    return {
        "current_path": target,
        "parent_path": parent,
        "directories": directories,
        "quick_jumps": quick_jumps
    }


def resolve_folder_path(raw_path: str, sample_files: Optional[List[str]] = None) -> Optional[str]:
    """
    Intelligently resolves a raw folder input (which might be just a folder name like
    'AI-Powered Intelligent Document Organization Agent' or 'Sample_College_Documents'
    or a relative path) to its real, absolute filesystem path.
    """
    cleaned = (raw_path or "").strip().strip('"').strip("'")
    if not cleaned:
        return None

    cwd = os.path.abspath(os.getcwd())
    cwd_name = os.path.basename(cwd)

    # 1. Direct path or normalized absolute path if already existing
    norm = os.path.normpath(cleaned)
    if os.path.isabs(norm) and os.path.isdir(norm):
        return norm
    if os.path.exists(norm) and os.path.isdir(norm):
        return os.path.abspath(norm)

    cleaned_lower = cleaned.lower()

    # 2. Check if cleaned matches current working directory name or shorthand
    if cleaned_lower in [cwd_name.lower(), ".", "current", "workspace", "root"]:
        return cwd

    # 3. Check if cleaned matches sample documents folder
    sample_dir = os.path.join(cwd, "Sample_College_Documents")
    if cleaned_lower in ["sample", "sample documents", "sample folder", "sample_college_documents", "college documents", "sample_college_documents/"]:
        if os.path.isdir(sample_dir):
            return sample_dir

    # 4. Check if cleaned is a direct subfolder inside cwd or parent
    direct_sub = os.path.join(cwd, cleaned)
    if os.path.isdir(direct_sub):
        return os.path.abspath(direct_sub)

    parent_cwd = os.path.dirname(cwd)
    parent_sub = os.path.join(parent_cwd, cleaned)
    if os.path.isdir(parent_sub):
        return os.path.abspath(parent_sub)

    # 5. Build candidate standard directories
    home = os.path.expanduser("~")
    candidates = [
        cwd,
        sample_dir,
        direct_sub,
        parent_sub,
        os.path.join(home, "Downloads", cleaned),
        os.path.join(home, "Documents", cleaned),
        os.path.join(home, "Desktop", cleaned),
        os.path.join(home, cleaned),
        os.path.join(home, "Downloads"),
        os.path.join(home, "Documents"),
    ]
    if sys.platform == "win32":
        candidates.extend([
            os.path.join("C:\\", cleaned),
            os.path.join("D:\\", cleaned),
        ])

    # 6. If sample files from file picker are provided, match the candidate containing them
    if sample_files:
        for c in candidates:
            if os.path.isdir(c):
                matched = any(os.path.exists(os.path.join(c, sf)) for sf in sample_files)
                if matched:
                    return os.path.abspath(c)

    # 7. Check if candidate basename or direct subpath matches cleaned
    for c in candidates:
        if os.path.isdir(c):
            if os.path.basename(c).lower() == cleaned_lower:
                return os.path.abspath(c)
            sub = os.path.join(c, cleaned)
            if os.path.isdir(sub):
                return os.path.abspath(sub)

    # 8. Check direct subdirectories of cwd for case-insensitive match
    try:
        with os.scandir(cwd) as it:
            for entry in it:
                if entry.is_dir() and entry.name.lower() == cleaned_lower:
                    return os.path.abspath(entry.path)
    except Exception:
        pass

    # 9. Fallback if any candidate exists
    for c in candidates:
        if os.path.isdir(c):
            return os.path.abspath(c)

    return None


@app.post("/api/folder/resolve-path")
def api_resolve_folder_path(payload: Dict[str, Any] = Body(...)):
    """
    Takes a folder name (e.g. 'Sample_College_Documents') or partial path and optional sample filenames,
    and returns the real, absolute filesystem path.
    """
    raw_name = (payload.get("name") or payload.get("folder_path") or "").strip()
    sample_files = payload.get("files") or []
    resolved = resolve_folder_path(raw_name, sample_files)
    if resolved:
        return {"resolved": True, "path": resolved, "message": f"Resolved path: {resolved}"}
    return {"resolved": False, "path": None, "message": f"Could not find absolute path for: {raw_name}"}


@app.post("/api/folder/generate-sample")
def api_generate_sample():
    """Generates sample college documents and immediately returns scanned analysis."""
    sample_root = generate_sample_college_documents()
    return scan_folder({"folder_path": sample_root})



@app.post("/api/folder/validate")
def validate_folder_path(payload: Dict[str, Any] = Body(...)):
    """
    Validates user entered path:
    1. Checks if path exists (auto-resolving folder names like 's')
    2. Confirms it points to a directory
    3. Checks read permissions and write access
    4. Counts supported documents without modifying filesystem
    """
    raw_path = (payload.get("folder_path") or "").strip().strip('"').strip("'")
    if not raw_path:
        return {"valid": False, "error": "Folder path cannot be empty."}

    resolved = resolve_folder_path(raw_path)
    norm_path = resolved if resolved else os.path.normpath(raw_path)

    if not os.path.exists(norm_path):
        return {"valid": False, "error": f"Path does not exist on disk: {norm_path}"}

    if not os.path.isdir(norm_path):
        return {"valid": False, "error": f"Specified path is a file, not a directory: {norm_path}"}

    if not os.access(norm_path, os.R_OK):
        return {"valid": False, "error": f"Read permission denied for directory: {norm_path}"}

    is_writable = os.access(norm_path, os.W_OK)

    # Count supported documents
    supported_exts = {".pdf", ".docx", ".doc", ".xlsx", ".xls", ".txt", ".csv", ".md"}
    doc_count = 0
    try:
        for root, dirs, files in os.walk(norm_path):
            dirs[:] = [d for d in dirs if not d.startswith(('.', '$'))]
            for f in files:
                if f.startswith(('.', '$', '~')):
                    continue
                if os.path.splitext(f)[1].lower() in supported_exts:
                    doc_count += 1
    except Exception:
        pass

    return {
        "valid": True,
        "folder_path": norm_path,
        "is_writable": is_writable,
        "doc_count": doc_count,
        "message": f"Path is valid and accessible ({doc_count} supported documents found)."
    }


@app.post("/api/folder/create")
def create_new_folder(payload: Dict[str, Any] = Body(...)):
    """
    Creates a new folder in an explicitly chosen parent directory.
    """
    parent_dir = (payload.get("parent_dir") or "").strip()
    folder_name = (payload.get("folder_name") or "").strip()

    if not parent_dir or not os.path.isdir(parent_dir):
        raise HTTPException(status_code=400, detail="Parent directory must exist on disk.")

    if not folder_name:
        raise HTTPException(status_code=400, detail="Folder name is required.")

    clean_name = re.sub(r'[\\/*?:"<>|]', "", folder_name).strip()
    if not clean_name or clean_name in [".", ".."]:
        raise HTTPException(status_code=400, detail="Invalid folder name.")

    new_path = os.path.join(parent_dir, clean_name)
    if os.path.exists(new_path):
        raise HTTPException(status_code=400, detail=f"A folder or file named '{clean_name}' already exists.")

    try:
        os.makedirs(new_path)
        record_activity("FOLDER_CREATED", new_path, f"Created new folder '{clean_name}'")
        return {
            "success": True,
            "folder_path": new_path,
            "message": f"Successfully created folder: {clean_name}"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to create folder: {str(e)}")


@app.post("/api/folder/upload")
async def upload_documents(
    target_folder: Optional[str] = None,
    files: List[UploadFile] = File(...)
):
    """
    Uploads individual supported documents to target folder or a dedicated staging folder.
    """
    base_target = target_folder or active_session.get("current_folder")
    if not base_target or not os.path.isdir(base_target):
        workspace = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        base_target = os.path.join(workspace, "Uploaded_Documents")
        os.makedirs(base_target, exist_ok=True)

    saved_files = []
    for f in files:
        if not f.filename:
            continue
        clean_name = os.path.basename(f.filename)
        dest_path = os.path.join(base_target, clean_name)
        with open(dest_path, "wb") as out_f:
            out_f.write(await f.read())
        saved_files.append({"file_name": clean_name, "path": dest_path})

    record_activity("FILES_UPLOADED", base_target, f"Uploaded {len(saved_files)} documents to {base_target}")
    return {
        "success": True,
        "target_folder": base_target,
        "uploaded_count": len(saved_files),
        "files": saved_files,
        "message": f"Successfully stored {len(saved_files)} files in '{base_target}'"
    }


@app.post("/api/folder/scan")
def scan_folder(payload: Dict[str, Any] = Body(...)):
    """
    Read-only scan of user's selected folder:
    - Parses files without modifying filesystem
    - Extracts text, classifies categories, computes confidence
    - Detects cross-document relationships
    - Builds live visual previews
    """
    raw_path = (payload.get("folder_path") or "").strip().strip('"').strip("'")
    if not raw_path:
        raise HTTPException(status_code=400, detail="A valid folder path must be provided.")

    resolved = resolve_folder_path(raw_path)
    if not resolved:
        raise HTTPException(status_code=400, detail=f"Could not find or access directory: '{raw_path}'. Please check that the folder exists.")

    folder_path = resolved
    record_activity("SCAN_INITIATED", folder_path, "Started read-only scan of folder")

    # 1. Read directory tree
    try:
        dir_scan = scan_directory_tree(folder_path)
    except Exception as e:
        record_activity("SCAN_ERROR", folder_path, str(e), status="FAILED")
        raise HTTPException(status_code=400, detail=f"Failed to scan folder: {str(e)}")

    doc_files = dir_scan["document_files"]
    extracted_docs = []

    # 2. Extract content safely
    for doc in doc_files:
        content_info = extract_document_content(doc["file_path"])
        extracted_docs.append(content_info)

    # 3. Classify each document
    classification_preview = []
    custom_cats = active_session["custom_categories"]
    for doc in extracted_docs:
        cls_result = classify_document(doc["file_name"], doc.get("text", ""), custom_cats)
        
        # Summary snippet for ledger
        raw_text = doc.get("text", "")
        snippet = raw_text[:220] + "..." if len(raw_text) > 220 else raw_text

        preview_item = {
            "id": str(uuid.uuid4())[:8],
            "file_name": doc["file_name"],
            "current_location": doc["file_path"],
            "extension": doc["extension"],
            "size_bytes": doc["size_bytes"],
            "suggested_category": cls_result["suggested_category"],
            "category": cls_result["suggested_category"],  # Active working category
            "original_ai_category": cls_result["suggested_category"],
            "proposed_subfolder": cls_result["proposed_subfolder"],
            "confidence_score": cls_result["confidence_score"],
            "needs_review": cls_result["needs_review"],
            "review_reason": cls_result["review_reason"],
            "evidence": cls_result["evidence"],
            "is_user_edited": False,
            "summary_snippet": snippet
        }
        classification_preview.append(preview_item)

    # 4. Detect related documents
    related_map = find_related_documents([
        {"file_name": d["file_name"], "file_path": d["current_location"], 
         "suggested_category": d["category"], "text": ext.get("text", "")}
        for d, ext in zip(classification_preview, extracted_docs)
    ])

    # Attach related items into preview records
    for item in classification_preview:
        item["related_documents"] = related_map.get(item["file_name"], [])

    # 5. Build proposed preview tree
    proposed_tree = build_proposed_tree(folder_path, classification_preview)

    # Save to session
    active_session["current_folder"] = folder_path
    active_session["scanned_documents"] = extracted_docs
    active_session["classification_preview"] = classification_preview
    active_session["related_map"] = related_map

    record_activity("SCAN_COMPLETED", folder_path, f"Successfully analyzed {len(classification_preview)} documents in read-only mode.")

    return {
        "success": True,
        "folder_path": folder_path,
        "total_documents": len(classification_preview),
        "current_tree": dir_scan["tree"],
        "proposed_tree": proposed_tree,
        "classification_preview": classification_preview,
        "available_categories": list(set(get_available_categories() + custom_cats))
    }


@app.post("/api/folder/generate-sample")
def generate_sample_folder():
    """Generates realistic College_Documents dataset for instant testing."""
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    samples_dir = os.path.join(base_dir, "test_samples")
    os.makedirs(samples_dir, exist_ok=True)
    sample_path = generate_sample_college_documents(samples_dir)

    record_activity("SAMPLE_GENERATED", sample_path, "Generated sample College_Documents test suite.")
    # Automatically scan the newly generated sample folder
    return scan_folder({"folder_path": sample_path})


@app.post("/api/preview/update-category")
def update_category(payload: Dict[str, Any] = Body(...)):
    """
    Manually edits the category for a file during read-only preview mode.
    Does NOT move the file. Immediately updates the preview table & proposed folder tree.
    """
    file_name = payload.get("file_name")
    new_category = payload.get("new_category", "").strip()

    if not file_name or not new_category:
        raise HTTPException(status_code=400, detail="File name and new category are required.")

    # Register custom category if new
    if new_category not in active_session["custom_categories"] and new_category not in get_available_categories():
        active_session["custom_categories"].append(new_category)

    updated_item = None
    for item in active_session["classification_preview"]:
        if item["file_name"] == file_name:
            item["category"] = new_category
            item["proposed_subfolder"] = new_category.replace(" ", "_")
            item["is_user_edited"] = True
            item["needs_review"] = False
            item["review_reason"] = "Manually corrected by user."
            updated_item = item
            break

    if not updated_item:
        raise HTTPException(status_code=404, detail=f"File {file_name} not found in current preview session.")

    record_activity("PREVIEW_EDITED", active_session["current_folder"] or "", 
                    f"User changed category for {file_name} to '{new_category}' (In-memory preview).")

    proposed_tree = build_proposed_tree(active_session["current_folder"], active_session["classification_preview"])

    return {
        "success": True,
        "updated_item": updated_item,
        "proposed_tree": proposed_tree,
        "available_categories": list(set(get_available_categories() + active_session["custom_categories"]))
    }


@app.post("/api/preview/reset")
def reset_preview():
    """Discards all manual edits and resets categories back to AI suggestions."""
    if not active_session["classification_preview"]:
        raise HTTPException(status_code=400, detail="No active preview to reset.")

    for item in active_session["classification_preview"]:
        item["category"] = item["original_ai_category"]
        item["proposed_subfolder"] = item["original_ai_category"].replace(" ", "_")
        item["is_user_edited"] = False

    proposed_tree = build_proposed_tree(active_session["current_folder"], active_session["classification_preview"])

    record_activity("PREVIEW_RESET", active_session["current_folder"] or "", "User reset classification preview to defaults.")

    return {
        "success": True,
        "classification_preview": active_session["classification_preview"],
        "proposed_tree": proposed_tree
    }


@app.post("/api/organization/approve")
def request_approval_token():
    """
    Step 5 of workflow: Generates a temporary approval token and summary of the proposed moves.
    Requires explicit user review before write permission is granted.
    """
    if not active_session["classification_preview"]:
        raise HTTPException(status_code=400, detail="No documents available to organize.")

    token = f"APP-{uuid.uuid4().hex[:12].upper()}"
    active_session["pending_token"] = token

    summary_by_cat = {}
    for item in active_session["classification_preview"]:
        cat = item["category"]
        summary_by_cat[cat] = summary_by_cat.get(cat, 0) + 1

    return {
        "success": True,
        "approval_token": token,
        "folder_path": active_session["current_folder"],
        "total_files": len(active_session["classification_preview"]),
        "breakdown": summary_by_cat,
        "warning": "Approving will create subfolders inside the original folder and move files into their destinations."
    }


@app.post("/api/organization/execute")
def execute_organization(payload: Dict[str, Any] = Body(...)):
    """
    Step 6 of workflow: Atomic execution of approved moves.
    Validates token, moves files, creates subfolders in original folder,
    updates SQLite ledger and undo snapshots.
    """
    token = payload.get("approval_token")
    if not token or token != active_session.get("pending_token"):
        raise HTTPException(status_code=403, detail="Invalid or expired approval token.")

    base_folder = active_session["current_folder"]
    plan = active_session["classification_preview"]

    try:
        result = execute_approved_organization(base_folder, plan, token)
        active_session["pending_token"] = None
        active_session["last_batch_id"] = result["batch_id"]
        
        # Rescan to update current tree
        dir_scan = scan_directory_tree(base_folder)

        return {
            "success": True,
            "result": result,
            "updated_tree": dir_scan["tree"],
            "can_undo": True
        }
    except Exception as e:
        record_activity("EXECUTE_ERROR", base_folder or "", str(e), status="FAILED")
        raise HTTPException(status_code=500, detail=f"File organization error: {str(e)}")


@app.post("/api/organization/undo")
def undo_last_move(payload: Dict[str, Any] = Body(default={})):
    """Reverts files from the last organization batch back to original paths."""
    batch_id = payload.get("batch_id") or active_session.get("last_batch_id")
    res = undo_organization(batch_id)
    if not res.get("success"):
        raise HTTPException(status_code=400, detail=res.get("message", "Undo failed."))

    # Rescan current folder if active
    updated_tree = None
    if active_session["current_folder"] and os.path.exists(active_session["current_folder"]):
        dir_scan = scan_directory_tree(active_session["current_folder"])
        updated_tree = dir_scan["tree"]

    return {
        "success": True,
        "result": res,
        "updated_tree": updated_tree,
        "can_undo": get_latest_undo_batch() is not None
    }


@app.get("/api/ledger/search")
def search_documents_ledger(
    query: str = "",
    category: str = "",
    status: str = "",
    limit: int = 100
):
    """Searches the SQLite document ledger."""
    records = search_ledger(query=query, category=category, status=status, limit=limit)
    return {"records": records, "count": len(records)}


@app.post("/api/ledger/open-file")
def open_document_file(payload: Dict[str, Any] = Body(...)):
    """Opens a document locally in the user's default OS application."""
    file_path = payload.get("file_path")
    if not file_path or not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="File does not exist on disk.")

    try:
        if sys.platform == "win32":
            os.startfile(file_path)
        elif sys.platform == "darwin":
            subprocess.run(["open", file_path], check=True)
        else:
            subprocess.run(["xdg-open", file_path], check=True)
        return {"success": True, "message": f"Opened {os.path.basename(file_path)}"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to open file: {str(e)}")


@app.post("/api/ledger/open-folder")
def open_document_folder(payload: Dict[str, Any] = Body(...)):
    """Reveals the file or folder in Windows Explorer."""
    target_path = payload.get("path")
    if not target_path or not os.path.exists(target_path):
        raise HTTPException(status_code=404, detail="Path does not exist on disk.")

    try:
        if sys.platform == "win32":
            if os.path.isfile(target_path):
                subprocess.run(["explorer", f"/select,{os.path.normpath(target_path)}"])
            else:
                subprocess.run(["explorer", os.path.normpath(target_path)])
        return {"success": True, "message": "Opened in File Explorer"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to open File Explorer: {str(e)}")


@app.get("/api/audit/logs")
def fetch_audit_logs():
    """Returns recent activity and security audit entries."""
    logs = get_audit_logs(limit=60)
    return {"logs": logs}


# ============================================================================
# Conversational AI Agent (Chatbot Engine)
# ============================================================================

@app.post("/api/chat")
def process_chat_message(payload: Dict[str, Any] = Body(...)):
    """
    Processes natural-language instructions from the chatbot interface:
    - "organize files in this folder"
    - "change [file] to [category]"
    - "show me scholarship-related documents"
    - "proceed with organization"
    - "undo last organization"
    - "status" / "help"
    """
    message = payload.get("message", "").strip()
    if not message:
        return {"response": "Please provide an instruction or question."}

    msg_lower = message.lower()

    # 1. "Organize files in this folder" / "scan folder"
    if any(k in msg_lower for k in ["organize files in this folder", "scan this folder", "scan folder", "start scan"]):
        if not active_session["current_folder"]:
            return {
                "response": "Please select the folder you want to organize using the 'Browse Folder' or 'Use Sample Folder' button.",
                "action": "PROMPT_FOLDER_SELECT"
            }
        # Run scan
        scan_res = scan_folder({"folder_path": active_session["current_folder"]})
        count = scan_res["total_documents"]
        return {
            "response": f"I found {count} documents. I have prepared a classification preview in read-only mode. No files have been moved.",
            "action": "SCAN_COMPLETED",
            "data": scan_res
        }

    # 2. "Change <filename> to <category>"
    change_match = re.search(r'change\s+([a-zA-Z0-9_\-\.\s]+?)\s+to\s+([a-zA-Z0-9_\-\s]+)', message, re.IGNORECASE)
    if change_match:
        target_fn = change_match.group(1).strip()
        target_cat = change_match.group(2).strip()

        # Fuzzy match filename if user wrote partial
        matched_item = None
        for item in active_session["classification_preview"]:
            if item["file_name"].lower() == target_fn.lower() or target_fn.lower() in item["file_name"].lower():
                matched_item = item
                break

        if matched_item:
            res = update_category({"file_name": matched_item["file_name"], "new_category": target_cat.title()})
            return {
                "response": f"The category for '{matched_item['file_name']}' has been updated to '{target_cat.title()}' in the preview. No files have been moved.",
                "action": "CATEGORY_UPDATED",
                "data": res
            }
        else:
            return {
                "response": f"I couldn't find a file matching '{target_fn}' in the current preview list.",
                "action": "FILE_NOT_FOUND"
            }

    # 3. "Show me all scholarship-related documents" / search query
    show_match = re.search(r'show\s+(?:me\s+)?(?:all\s+)?([a-zA-Z0-9_\-\s]+?)(?:-related)?\s+documents?', msg_lower)
    if show_match or "show" in msg_lower and "documents" in msg_lower:
        query_term = show_match.group(1).strip() if show_match else msg_lower.replace("show", "").replace("documents", "").strip()
        # Search in active preview or ledger
        matching_preview = []
        for item in active_session["classification_preview"]:
            if query_term in item["file_name"].lower() or query_term in item["category"].lower():
                matching_preview.append(item)

        if matching_preview:
            bullet_list = "\n".join([f"• **{m['file_name']}** ({m['category']}) - Related docs: {len(m.get('related_documents', []))}" for m in matching_preview[:8]])
            return {
                "response": f"Here are the matching documents for '{query_term}':\n\n{bullet_list}",
                "action": "SHOW_DOCUMENTS",
                "filter": query_term
            }
        else:
            # Query SQLite ledger
            ledger_hits = search_ledger(query=query_term, limit=10)
            if ledger_hits:
                bullet_list = "\n".join([f"• **{m['file_name']}** ({m['category']}) in {m['current_location']}" for m in ledger_hits[:8]])
                return {
                    "response": f"Found {len(ledger_hits)} records in the document ledger:\n\n{bullet_list}",
                    "action": "LEDGER_RESULTS"
                }
            return {
                "response": f"No documents found matching '{query_term}' in current preview or document ledger.",
                "action": "NO_MATCH"
            }

    # 4. "Proceed with organization" / "approve"
    if any(k in msg_lower for k in ["proceed with organization", "approve organization", "confirm organization", "execute organization"]):
        if not active_session["classification_preview"]:
            return {"response": "Please scan a folder first to generate a classification preview before proceeding."}
        
        # Initiate approval gate
        appr = request_approval_token()
        breakdown_str = ", ".join([f"{cat}: {cnt}" for cat, cnt in appr["breakdown"].items()])
        return {
            "response": f"I have prepared the final organization plan for {appr['total_files']} documents ({breakdown_str}).\n\n"
                        f"🛡️ **Safety Gate**: Before any file is moved, please review the confirmation dialog and click **Confirm & Organize**.",
            "action": "SHOW_APPROVAL_MODAL",
            "token_info": appr
        }

    # 5. "Undo" / "Revert"
    if "undo" in msg_lower or "revert" in msg_lower:
        latest = get_latest_undo_batch()
        if not latest:
            return {"response": "There are no previous organization moves available to undo."}
        undo_res = undo_last_move({})
        return {
            "response": f"Successfully reverted: {undo_res['result']['message']}",
            "action": "UNDO_COMPLETED",
            "data": undo_res
        }

    # Default fallback
    return {
        "response": "I am your AI Document Organization Agent. You can give me commands like:\n"
                    "• *'Organize the files in this folder'*\n"
                    "• *'Change College_Circular.pdf to Academic'*\n"
                    "• *'Show me all scholarship-related documents'*\n"
                    "• *'Proceed with organization'*\n"
                    "• *'Undo last organization'*",
        "action": "HELP"
    }


# ============================================================================
# Static Files & Frontend Mount
# ============================================================================
frontend_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "frontend")
if os.path.exists(frontend_dir):
    app.mount("/", StaticFiles(directory=frontend_dir, html=True), name="frontend")
