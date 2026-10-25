"""
Document Classification Engine.
Understands document purpose and context from filename and extracted content.
Suggests suitable categories, target folders, and calculates confidence scores.
Flags low-confidence classifications for explicit human review.
"""

import os
import re
from typing import Dict, Any, List, Tuple

# Comprehensive taxonomy and keyword weights for classification
CATEGORY_TAXONOMY = {
    "Exams": {
        "keywords": ["exam", "examination", "timetable", "schedule", "admit card", "hall ticket", "marksheet",
                     "grade card", "semester exam", "midterm", "final exam", "viva", "practical", "re-evaluation",
                     "question paper", "test score", "invigilation"],
        "patterns": [r"exam.*time", r"exam.*sched", r"hall.*ticket", r"admit.*card", r"grade.*sheet", r"marksheet"],
        "folder_name": "Exams"
    },
    "Fees": {
        "keywords": ["fee", "fees", "receipt", "tuition", "payment", "challan", "dues", "hostel fee",
                     "bus fee", "examination fee", "invoice", "transaction id", "paid amount", "installments",
                     "refund", "balance amount", "bank reference", "billing"],
        "patterns": [r"fee.*receipt", r"tuition.*fee", r"payment.*receipt", r"fee.*challan", r"billing.*statement"],
        "folder_name": "Fees"
    },
    "Scholarship": {
        "keywords": ["scholarship", "financial aid", "fellowship", "stipend", "grant", "income certificate",
                     "merit scholarship", "freeship", "caste certificate", "eligibility criteria",
                     "disbursement", "sanction letter", "renewal", "endowment"],
        "patterns": [r"scholarship.*app", r"scholarship.*guide", r"financial.*aid", r"income.*cert"],
        "folder_name": "Scholarship"
    },
    "Placement": {
        "keywords": ["placement", "recruitment", "interview", "campus drive", "offer letter", "resume",
                     "curriculum vitae", "job offer", "internship", "package", "ctc", "company shortlist",
                     "aptitude test", "hiring notice", "training & placement"],
        "patterns": [r"placement.*notice", r"campus.*drive", r"offer.*letter", r"interview.*sched", r"internship.*offer"],
        "folder_name": "Placement"
    },
    "Academic": {
        "keywords": ["syllabus", "curriculum", "course", "lecture", "assignment", "lab manual", "project report",
                     "study material", "academic calendar", "handbook", "faculty", "textbook", "notes", "thesis",
                     "dissertation", "seminar", "workshop", "attendance"],
        "patterns": [r"academic.*cal", r"course.*syl", r"lab.*manual", r"project.*rep", r"study.*mat"],
        "folder_name": "Academic"
    },
    "Circulars": {
        "keywords": ["circular", "notice", "announcement", "memorandum", "notification", "advisory", "order",
                     "principal", "dean office", "registrar", "office order", "gazette", "press release"],
        "patterns": [r"college.*circ", r"office.*order", r"urgent.*notice", r"public.*notif"],
        "folder_name": "Circulars"
    },
    "Identity & Records": {
        "keywords": ["identity card", "id card", "aadhaar", "passport", "birth certificate", "bonafide",
                     "transfer certificate", "migration", "transcript", "provisional certificate", "degree",
                     "character certificate"],
        "patterns": [r"id.*card", r"bonafide.*cert", r"transfer.*cert", r"transcripts?"],
        "folder_name": "Identity_and_Records"
    },
    "Administrative": {
        "keywords": ["administration", "leave application", "noc", "permission", "undertaking", "affidavit",
                     "hostel allocation", "library card", "complaint", "feedback form", "requisition", "declaration"],
        "patterns": [r"leave.*app", r"noc.*letter", r"hostel.*alloc", r"undertaking.*form"],
        "folder_name": "Administrative"
    }
}


def classify_document(file_name: str, extracted_text: str, custom_categories: List[str] = None) -> Dict[str, Any]:
    """
    Classifies a document based on its name and extracted contents.
    Calculates confidence score and evidence.
    Flags low confidence when unsure.
    """
    name_lower = file_name.lower()
    text_lower = (extracted_text or "").lower()
    
    # Combined search space (filename has 3x weight because filenames often accurately summarize the doc)
    scores: Dict[str, float] = {}
    evidence: Dict[str, List[str]] = {}

    # Initialize taxonomy
    taxonomy = dict(CATEGORY_TAXONOMY)
    if custom_categories:
        for cat in custom_categories:
            if cat not in taxonomy:
                words = [w for w in re.split(r'[\s_\-]+', cat.lower()) if len(w) > 2]
                taxonomy[cat] = {
                    "keywords": words,
                    "patterns": [cat.lower()],
                    "folder_name": cat.replace(" ", "_")
                }

    for category, config in taxonomy.items():
        cat_score = 0.0
        found_matches = []

        # 1. Regex Pattern matching on filename
        for pat in config.get("patterns", []):
            if re.search(pat, name_lower):
                cat_score += 4.0
                found_matches.append(f"Filename matches pattern '{pat}'")

        # 2. Exact keyword matching in filename
        for kw in config["keywords"]:
            if kw in name_lower:
                cat_score += 3.0
                found_matches.append(f"Filename contains '{kw}'")

        # 3. Content matching
        if text_lower:
            for kw in config["keywords"]:
                count = text_lower.count(kw)
                if count > 0:
                    added_score = min(count * 0.8, 4.0)
                    cat_score += added_score
                    if added_score >= 1.5 and kw not in [m.split("'")[1] for m in found_matches if "'" in m]:
                        found_matches.append(f"Content mentions '{kw}' ({count}x)")

        scores[category] = cat_score
        evidence[category] = found_matches

    # Sort categories by score
    sorted_categories = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    best_category, top_score = sorted_categories[0]
    runner_up_score = sorted_categories[1][1] if len(sorted_categories) > 1 else 0.0

    # Calculate confidence score
    if top_score == 0:
        suggested_category = "Miscellaneous"
        confidence = 0.25
        needs_review = True
        reason = "No matching document patterns or keywords found in filename or content."
        folder_name = "Miscellaneous"
    else:
        # Confidence formula considers absolute score and margin over runner-up
        margin = top_score - runner_up_score
        raw_conf = min(0.98, 0.45 + (top_score * 0.07) + (margin * 0.05))
        confidence = round(raw_conf, 2)
        
        # Low confidence threshold
        if confidence < 0.65 or margin < 1.0:
            needs_review = True
            reason = f"Low distinction between '{best_category}' and '{sorted_categories[1][0]}'."
        else:
            needs_review = False
            reason = None

        suggested_category = best_category
        folder_name = taxonomy[best_category]["folder_name"]

    top_evidence = evidence.get(suggested_category, [])

    return {
        "file_name": file_name,
        "suggested_category": suggested_category,
        "proposed_subfolder": folder_name,
        "confidence_score": confidence,
        "needs_review": needs_review,
        "review_reason": reason,
        "evidence": top_evidence[:4],
        "all_scores": {k: round(v, 2) for k, v in scores.items() if v > 0}
    }


def get_available_categories() -> List[str]:
    """Returns list of all default recognized categories."""
    return list(CATEGORY_TAXONOMY.keys()) + ["Miscellaneous"]
