"""
Native OS Folder Selection & Filesystem Scanner.
Pops the native Windows/OS folder picker dialog safely and securely via Tkinter.
Also validates folder permissions and performs read-only directory tree scans.
"""

import os
import sys
import subprocess
from typing import Optional, Dict, Any, List


def open_native_folder_picker() -> Optional[str]:
    """
    Invokes the standalone picker dialog in a separate process.
    This guarantees that the native OS folder picker runs on the main GUI thread,
    pops directly in the foreground, and does not conflict with FastAPI/Uvicorn.
    """
    picker_script = os.path.join(os.path.dirname(__file__), "picker_dialog.py")
    try:
        res = subprocess.run(
            [sys.executable, picker_script],
            capture_output=True,
            text=True,
            timeout=25
        )
        if res.returncode == 0:
            output = res.stdout.strip()
            return output if output else None
        return None
    except (subprocess.TimeoutExpired, Exception):
        return None


def scan_directory_tree(folder_path: str, max_depth: int = 3) -> Dict[str, Any]:
    """
    Recursively scans a directory in read-only mode to build the folder tree.
    Returns:
    - Root folder path
    - Total files found
    - Hierarchical tree structure
    - Supported document files list
    """
    if not os.path.isdir(folder_path):
        raise ValueError(f"Path is not a valid directory: {folder_path}")

    # Check read permissions
    if not os.access(folder_path, os.R_OK):
        raise PermissionError(f"Read permission denied for folder: {folder_path}")

    supported_extensions = {".pdf", ".docx", ".doc", ".xlsx", ".xls", ".txt", ".csv", ".md"}

    def build_node(current_path: str, depth: int) -> Dict[str, Any]:
        node_name = os.path.basename(current_path) or current_path
        children = []
        files = []

        if depth <= max_depth:
            try:
                entries = sorted(os.scandir(current_path), key=lambda e: (not e.is_dir(), e.name.lower()))
                for entry in entries:
                    if entry.name.startswith(('.', '$')):  # Skip hidden/system files
                        continue
                    if entry.is_dir(follow_symlinks=False):
                        children.append(build_node(entry.path, depth + 1))
                    elif entry.is_file(follow_symlinks=False):
                        ext = os.path.splitext(entry.name)[1].lower()
                        files.append({
                            "name": entry.name,
                            "path": entry.path,
                            "extension": ext,
                            "size": entry.stat().st_size,
                            "supported": ext in supported_extensions
                        })
            except PermissionError:
                pass

        return {
            "name": node_name,
            "path": current_path,
            "type": "directory",
            "children": children,
            "files": files
        }

    tree = build_node(folder_path, 1)

    # Flatten list of all supported documents in the root folder (and immediate subfolders)
    document_files = []
    try:
        for root, dirs, fnames in os.walk(folder_path):
            # Ignore hidden directories
            dirs[:] = [d for d in dirs if not d.startswith(('.', '$'))]
            for fn in fnames:
                if fn.startswith(('.', '$', '~')):
                    continue
                ext = os.path.splitext(fn)[1].lower()
                if ext in supported_extensions:
                    full_p = os.path.join(root, fn)
                    try:
                        document_files.append({
                            "file_name": fn,
                            "file_path": full_p,
                            "extension": ext,
                            "size_bytes": os.path.getsize(full_p),
                            "relative_path": os.path.relpath(full_p, folder_path)
                        })
                    except OSError:
                        pass
    except Exception as e:
        pass

    return {
        "root_path": folder_path,
        "tree": tree,
        "total_documents": len(document_files),
        "document_files": document_files
    }
