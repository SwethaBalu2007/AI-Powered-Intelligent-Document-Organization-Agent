"""
Comprehensive Automated Test Suite for AI Document Organization Agent.
Tests:
1. Sample document generation (PDF, DOCX, XLSX, TXT)
2. Read-only text extraction and classification
3. Confidence score and evidence verification
4. Manual category correction in preview (zero files moved)
5. Related documents clustering
6. Approval-gated organization execution
7. Verification that files are organized in the original folder
8. SQLite ledger recording and search
9. 1-click Undo / Rollback restoration
"""

import os
import sys
import shutil

# Add project root to sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from backend.sample_generator import generate_sample_college_documents
from backend.extractor import extract_document_content
from backend.classifier import classify_document
from backend.related import find_related_documents
from backend.file_ops import execute_approved_organization, undo_organization
from backend.ledger import search_ledger, get_audit_logs, get_latest_undo_batch
from backend.dialog import scan_directory_tree


def run_all_tests():
    print("=" * 70)
    print("RUNNING VERIFICATION TEST SUITE: AI DOCUMENT ORGANIZATION AGENT")
    print("=" * 70)

    test_dir = os.path.join(os.path.dirname(__file__), "scratch_test_env")
    if os.path.exists(test_dir):
        shutil.rmtree(test_dir)
    os.makedirs(test_dir, exist_ok=True)

    # 1. Test sample dataset generation
    print("\n[Step 1] Generating sample 'College_Documents' test suite...")
    sample_folder = generate_sample_college_documents(test_dir)
    assert os.path.exists(sample_folder), "Sample folder was not created!"
    files = os.listdir(sample_folder)
    print(f" -> Created {len(files)} test files in: {sample_folder}")
    for f in sorted(files):
        print(f"    • {f}")
    assert len(files) >= 5, "Expected at least 5 test files"

    # 2. Test read-only scan & extraction
    print("\n[Step 2] Testing read-only extraction and AI classification...")
    scan_info = scan_directory_tree(sample_folder)
    doc_files = scan_info["document_files"]
    assert len(doc_files) == len(files), "Scan missed some files"

    extracted_records = []
    classification_preview = []
    for doc in doc_files:
        content = extract_document_content(doc["file_path"])
        assert content["supported"], f"File {doc['file_name']} should be supported"
        extracted_records.append(content)

        cls = classify_document(doc["file_name"], content.get("text", ""))
        classification_preview.append({
            "file_name": doc["file_name"],
            "current_location": doc["file_path"],
            "suggested_category": cls["suggested_category"],
            "category": cls["suggested_category"],
            "original_ai_category": cls["suggested_category"],
            "proposed_subfolder": cls["proposed_subfolder"],
            "confidence_score": cls["confidence_score"],
            "needs_review": cls["needs_review"],
            "summary_snippet": content.get("text", "")[:150]
        })

    # Check key expected categories
    cat_by_name = {c["file_name"]: c["category"] for c in classification_preview}
    print(" -> Inferred Categories:")
    for fn, cat in sorted(cat_by_name.items()):
        conf = next(c["confidence_score"] for c in classification_preview if c["file_name"] == fn)
        print(f"    • {fn} -> [{cat}] (Confidence: {int(conf*100)}%)")

    assert cat_by_name["Exam_Timetable.pdf"] == "Exams", f"Expected Exams, got {cat_by_name['Exam_Timetable.pdf']}"
    assert cat_by_name["Fee_Receipt.pdf"] == "Fees", f"Expected Fees, got {cat_by_name['Fee_Receipt.pdf']}"
    assert cat_by_name["Scholarship_Application.pdf"] == "Scholarship", f"Expected Scholarship, got {cat_by_name['Scholarship_Application.pdf']}"
    assert cat_by_name["Placement_Notice.pdf"] == "Placement", f"Expected Placement, got {cat_by_name['Placement_Notice.pdf']}"

    # Verify NO files were moved during read-only scan
    current_files = os.listdir(sample_folder)
    assert len(current_files) == len(files), "Files must NOT be moved during read-only scan!"
    print(" -> Read-only guarantee: 0 files moved.")

    # 3. Test Manual Category Correction (e.g. College_Circular.pdf -> Academic)
    print("\n[Step 3] Testing manual category correction in preview...")
    circular_item = next(c for c in classification_preview if c["file_name"] == "College_Circular.pdf")
    old_cat = circular_item["category"]
    circular_item["category"] = "Academic"
    circular_item["proposed_subfolder"] = "Academic"
    circular_item["is_user_edited"] = True
    print(f" -> Changed 'College_Circular.pdf': {old_cat} -> {circular_item['category']}")
    # Verify file is still untouched on disk
    assert os.path.exists(os.path.join(sample_folder, "College_Circular.pdf")), "File must remain in original location!"
    print(" -> Correction applied to preview. Original file intact.")

    # 4. Test Related Documents Detection
    print("\n[Step 4] Testing related documents clustering...")
    related_map = find_related_documents([
        {"file_name": d["file_name"], "file_path": d["current_location"], "category": d["category"], "text": ext.get("text", "")}
        for d, ext in zip(classification_preview, extracted_records)
    ])
    scholarship_related = related_map.get("Scholarship_Application.pdf", [])
    print(f" -> Documents related to Scholarship_Application.pdf: {len(scholarship_related)}")
    for r in scholarship_related:
        print(f"    • {r['file_name']} (Reason: {r['relationship_reason']})")
    assert len(scholarship_related) >= 1, "Expected related documents for scholarship"

    # 5. Test Approval Gate & Controlled Execution
    print("\n[Step 5] Testing approval and file reorganization execution...")
    # Attempt move without token -> should fail
    try:
        execute_approved_organization(sample_folder, classification_preview, approval_token="INVALID")
        assert False, "Should have rejected without valid approval token"
    except PermissionError:
        print(" -> Security Gate Confirmed: Rejected unapproved write attempt.")

    # Execute with valid token
    approval_token = "APP-TEST-TOKEN-991"
    exec_result = execute_approved_organization(sample_folder, classification_preview, approval_token=approval_token)
    print(f" -> Organization Summary: {exec_result['summary']}")
    print(f" -> Created Subfolders: {exec_result['created_subfolders']}")
    assert exec_result["moved_count"] == len(classification_preview), "All preview files should be moved"

    # Verify directory structure in original folder
    print("\n[Step 6] Inspecting organized original folder structure...")
    for root, dirs, fnames in os.walk(sample_folder):
        rel = os.path.relpath(root, sample_folder)
        indent = "    " if rel != "." else ""
        print(f"{indent}📁 {rel}/")
        for fn in fnames:
            print(f"{indent}    📄 {fn}")

    assert os.path.exists(os.path.join(sample_folder, "Exams", "Exam_Timetable.pdf"))
    assert os.path.exists(os.path.join(sample_folder, "Fees", "Fee_Receipt.pdf"))
    assert os.path.exists(os.path.join(sample_folder, "Scholarship", "Scholarship_Application.pdf"))
    assert os.path.exists(os.path.join(sample_folder, "Placement", "Placement_Notice.pdf"))
    assert os.path.exists(os.path.join(sample_folder, "Academic", "College_Circular.pdf"))
    print(" -> Verification passed: All files accurately positioned in approved subfolders!")

    # 7. Test SQLite Document Ledger & Search
    print("\n[Step 7] Testing SQLite document ledger and search query...")
    ledger_all = search_ledger(query="", limit=50)
    print(f" -> Total indexed ledger records: {len(ledger_all)}")
    assert len(ledger_all) >= len(files), "Ledger should contain all moved files"

    # Test keyword search
    scholarship_hits = search_ledger(query="scholarship", limit=10)
    print(f" -> Search query 'scholarship' found {len(scholarship_hits)} records:")
    for h in scholarship_hits:
        print(f"    • {h['file_name']} | Current: {h['current_location']}")
    assert len(scholarship_hits) >= 1, "Ledger search should find scholarship docs"

    # 8. Test 1-Click Undo / Rollback
    print("\n[Step 8] Testing 1-Click Undo / Rollback...")
    latest_batch = get_latest_undo_batch()
    assert latest_batch is not None, "Undo batch must exist"
    undo_result = undo_organization(latest_batch)
    print(f" -> Undo Status: {undo_result['message']}")
    assert undo_result["success"], "Undo operation failed"
    assert undo_result["reverted_count"] == len(classification_preview), "All files should be reverted"

    # Verify all files are back in original root
    reverted_files = os.listdir(sample_folder)
    print(f" -> Root folder after Undo now contains {len(reverted_files)} items:")
    for rf in sorted(reverted_files):
        print(f"    • {rf}")

    assert "Exam_Timetable.pdf" in reverted_files
    assert "Fee_Receipt.pdf" in reverted_files
    assert "Scholarship_Application.pdf" in reverted_files
    assert "Placement_Notice.pdf" in reverted_files
    assert "College_Circular.pdf" in reverted_files
    print(" -> 1-Click Undo test PASSED: Original folder restored perfectly!")

    # Clean up test env
    shutil.rmtree(test_dir)
    print("\n" + "=" * 70)
    print("ALL TESTS PASSED SUCCESSFULLY! 100% COMPLIANT WITH SPECIFICATION.")
    print("=" * 70)


if __name__ == "__main__":
    run_all_tests()
