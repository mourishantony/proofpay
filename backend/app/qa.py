"""Deterministic deliverable QA for drawing PDFs.

The checks are rule-based on purpose: the payment guard relies on them, so a
prompt-injected PDF cannot talk the AI agent into releasing funds.
"""
import re
from dataclasses import asdict, dataclass
from pathlib import Path

import pymupdf as fitz

RULES: dict[str, str] = {
    "text_layer": "PDF has an extractable text layer",
    "title_block": "Title block has drawing no, revision, date, drawn by, checked by and scale",
    "revision_match": "Title block revision matches the revision agreed for this milestone",
    "open_items": "No open items left on the sheet (TBD / HOLD / TO BE CONFIRMED)",
    "bom_present": "A bill of materials is present",
    "bom_callouts": "Every BOM mark is called out on the drawing and every callout is in the BOM",
}
DEFAULT_CHECKLIST = list(RULES)

SEVERITY_PENALTY = {"critical": 35, "major": 15, "minor": 5}

SEP = r"\s*[:#]\s*"
TITLE_FIELDS = {
    "drawing_no": rf"DRAWING\s*(?:NO\.?|NUMBER){SEP}([A-Z0-9][A-Z0-9\-_/.]*)",
    "revision": rf"\bREV(?:ISION)?(?:\s*NO\.?)?{SEP}([A-Z0-9]{{1,3}})\b",
    "date": rf"\bDATE{SEP}(\d{{1,4}}[-/.]\d{{1,2}}[-/.]\d{{1,4}})",
    "drawn_by": rf"DRAWN\s*BY{SEP}([A-Z]{{2,}})",
    "checked_by": rf"CHECKED\s*BY{SEP}([A-Z]{{2,}})",
    "scale": rf"\bSCALE{SEP}(\d+\s*:\s*\d+|NTS)",
}
OPEN_ITEM_PATTERNS = [r"\bTBD\b", r"\bTBC\b", r"\bHOLD\b", r"TO\s+BE\s+CONFIRMED", r"\?\?"]
MARK = r"[A-Z]{1,2}\d{3}"
# ASTM / material designations that look like part marks but are specs (e.g. bolt grade A325).
SPEC_TOKENS = {"A307", "A325", "A490", "A500", "A529", "A563", "A572", "A588", "A992", "A123", "A153", "A270"}
BOM_ROW = re.compile(rf"^\s*({MARK})\s+(\d+)\s+(.+?)\s*$")


@dataclass
class Finding:
    rule: str
    severity: str  # critical | major | minor
    message: str
    evidence: str = ""


def extract_pages(path: Path) -> list[str]:
    with fitz.open(path) as doc:
        return [page.get_text("text") for page in doc]


def _parse_bom(lines: list[str]) -> tuple[list[dict], set[int]]:
    """Return BOM rows found after a 'BILL OF MATERIALS' header, and their line indexes."""
    rows, idx = [], set()
    in_bom = False
    for i, line in enumerate(lines):
        if re.search(r"BILL\s+OF\s+MATERIALS?|\bBOM\b", line, re.I):
            in_bom = True
            continue
        if in_bom:
            m = BOM_ROW.match(line)
            if m:
                rows.append({"mark": m.group(1), "qty": int(m.group(2)), "description": m.group(3)})
                idx.add(i)
            elif rows and line.strip() and not re.match(r"^\s*MARK\b", line, re.I):
                in_bom = False  # table ended
    return rows, idx


def run_checks(path: Path, expected_revision: str, checklist: list[str] | None = None, pass_score: int = 80) -> dict:
    enabled = set(checklist or DEFAULT_CHECKLIST)
    pages = extract_pages(path)
    text = "\n".join(pages)
    upper = text.upper()
    lines = text.splitlines()
    findings: list[Finding] = []

    if not upper.strip():
        findings.append(Finding("text_layer", "critical", "No extractable text - the PDF looks scanned or flattened.",
                                "Export the drawing with a text layer, or enable OCR."))
        return _result(findings, {}, len(pages), pass_score)

    extracted: dict = {}
    for key, pattern in TITLE_FIELDS.items():
        m = re.search(pattern, upper)
        extracted[key] = m.group(1).strip() if m else None

    if "title_block" in enabled:
        for key, value in extracted.items():
            if value is None:
                label = key.replace("_", " ").upper()
                findings.append(Finding("title_block", "major", f"Title block field missing: {label}",
                                        f"Expected a '{label}:' entry in the title block."))

    if "revision_match" in enabled and expected_revision:
        rev = extracted.get("revision")
        if rev and rev != expected_revision.upper():
            findings.append(Finding("revision_match", "critical",
                                    f"Revision mismatch: sheet shows REV {rev}, milestone requires REV {expected_revision.upper()}",
                                    "An outdated revision was submitted."))

    if "open_items" in enabled:
        for pat in OPEN_ITEM_PATTERNS:
            for m in re.finditer(pat, upper):
                line = next((ln for ln in lines if m.group(0) in ln.upper()), m.group(0))
                findings.append(Finding("open_items", "major", f"Open item on sheet: '{m.group(0)}'", line.strip()[:160]))

    bom_rows, bom_line_idx = _parse_bom(lines)
    extracted["bom"] = bom_rows

    if "bom_present" in enabled and not bom_rows:
        findings.append(Finding("bom_present", "critical", "No bill of materials found on the drawing."))

    if "bom_callouts" in enabled and bom_rows:
        bom_marks = {r["mark"] for r in bom_rows}
        drawing_text = "\n".join(ln for i, ln in enumerate(lines) if i not in bom_line_idx).upper()
        callouts = set(re.findall(rf"\b{MARK}\b", drawing_text)) - SPEC_TOKENS
        extracted["callouts"] = sorted(callouts)
        for mark in sorted(bom_marks - callouts):
            findings.append(Finding("bom_callouts", "major", f"BOM mark {mark} is not called out on the drawing",
                                    "Part listed in BOM but not shown/labelled."))
        for mark in sorted(callouts - bom_marks):
            findings.append(Finding("bom_callouts", "major", f"Callout {mark} on the drawing is missing from the BOM",
                                    "Part shown on drawing but not listed in BOM."))

    return _result(findings, extracted, len(pages), pass_score)


def _result(findings: list[Finding], extracted: dict, page_count: int, pass_score: int) -> dict:
    score = max(0, 100 - sum(SEVERITY_PENALTY[f.severity] for f in findings))
    has_critical = any(f.severity == "critical" for f in findings)
    return {
        "score": score,
        "passed": score >= pass_score and not has_critical,
        "pass_score": pass_score,
        "page_count": page_count,
        "findings": [asdict(f) for f in findings],
        "extracted": extracted,
    }
