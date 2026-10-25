"""
Related Documents Clustering and Entity Linker.
Identifies documents that belong to the same topic, event, course, or process
(e.g., Scholarship Application <-> Scholarship Guidelines <-> Checklist).
Avoids creating false relationships when similarity confidence is low.
"""

import os
import re
from typing import List, Dict, Any, Set


# Common thematic groupings for collegiate and institutional records
THEMATIC_GROUPS = {
    "scholarship": ["scholarship", "financial aid", "fellowship", "stipend", "freeship", "income cert"],
    "examination": ["exam", "timetable", "schedule", "admit card", "hall ticket", "marksheet", "result"],
    "fees_payment": ["fee", "receipt", "challan", "dues", "tuition", "hostel fee"],
    "placement_job": ["placement", "interview", "campus drive", "offer letter", "resume", "cv", "internship"],
    "academic_course": ["syllabus", "curriculum", "course", "assignment", "lab manual", "project report"],
    "admissions_admin": ["admission", "bonafide", "migration", "transfer cert", "identity card", "id card"],
    "circulars_notices": ["circular", "notice", "announcement", "notification"]
}


def extract_keywords_and_stems(file_name: str, text: str) -> Set[str]:
    """Extracts significant alphanumeric tokens and normalized keywords."""
    combined = f"{file_name} {file_name} {text[:1500]}".lower()
    # Normalize punctuation
    cleaned = re.sub(r'[^a-z0-9\s]', ' ', combined)
    tokens = [t for t in cleaned.split() if len(t) > 3]
    
    stop_words = {
        "this", "that", "with", "from", "have", "were", "been", "will", "your", "their",
        "about", "please", "document", "file", "folder", "page", "date", "name", "copy"
    }
    return {t for t in tokens if t not in stop_words}


def compute_thematic_theme(name: str, text: str) -> str:
    """Finds primary theme if any matches."""
    sample = f"{name} {text[:800]}".lower()
    for theme_name, theme_kws in THEMATIC_GROUPS.items():
        if any(kw in sample for kw in theme_kws):
            return theme_name
    return ""


def find_related_documents(documents: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    """
    Given a list of document classification dicts:
    [{file_name, file_path, category, text, ...}],
    computes related document links for each document based on:
    1. Strong thematic topic match (e.g. both are 'scholarship' or both are 'examination')
    2. Shared specific tokens (e.g., course code like 'CS101', student ID, or semester 'Sem 4')
    3. Category and strong token overlap
    """
    results: Dict[str, List[Dict[str, Any]]] = {}
    doc_profiles = []

    for doc in documents:
        fname = doc["file_name"]
        text = doc.get("text", "")
        category = doc.get("suggested_category", "") or doc.get("category", "")
        keywords = extract_keywords_and_stems(fname, text)
        theme = compute_thematic_theme(fname, text)
        
        # Look for specific codes like Sem-4, CS302, etc. (Exclude general years so they don't over-cluster)
        codes = set(re.findall(r'\b[a-z]{2,4}\-?\d{2,4}\b|\bsem(?:ester)?[\s\-_]?\d\b', f"{fname} {text[:500]}".lower()))

        doc_profiles.append({
            "file_name": fname,
            "file_path": doc.get("file_path", ""),
            "category": category,
            "theme": theme,
            "keywords": keywords,
            "codes": codes
        })

    # Cross-compare pairs
    for i, doc_a in enumerate(doc_profiles):
        fname_a = doc_a["file_name"]
        related_for_a = []

        for j, doc_b in enumerate(doc_profiles):
            if i == j:
                continue

            relation_reason = None
            strength = 0

            # 1. Shared specific institutional codes (e.g. Sem 4 or Course ID)
            shared_codes = doc_a["codes"].intersection(doc_b["codes"])
            if shared_codes:
                strength += 2
                relation_reason = f"Shared reference: {', '.join(list(shared_codes)[:2])}"

            # 2. Both belong to same thematic group
            if doc_a["theme"] and doc_a["theme"] == doc_b["theme"]:
                strength += 2
                if not relation_reason:
                    theme_display = doc_a["theme"].replace("_", " ").title()
                    relation_reason = f"Same domain: {theme_display}"

            # 3. Same category + token overlap
            if doc_a["category"] and doc_a["category"] == doc_b["category"]:
                shared_kws = doc_a["keywords"].intersection(doc_b["keywords"])
                if len(shared_kws) >= 2:
                    strength += 1
                    if not relation_reason:
                        relation_reason = f"Category match ({doc_a['category']}) with shared keywords"

            # Threshold for genuine relationship
            if strength >= 2 and relation_reason:
                related_for_a.append({
                    "file_name": doc_b["file_name"],
                    "file_path": doc_b["file_path"],
                    "category": doc_b["category"],
                    "relationship_reason": relation_reason
                })

        results[fname_a] = related_for_a

    return results
