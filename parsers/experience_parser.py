"""
experience_parser.py

Computes academic / industry / research / administrative / total experience
from a structured list of work-history entries (the `detailed_experience`
array your LLM extraction step should already be producing).

Why the old `parse_experience(text)` approach failed
------------------------------------------------------
It tried to regex-parse free-form resume *text* for date ranges line by
line, splitting each line on "-" — which breaks the moment a date itself
is written as "2021-01" (the hyphen inside the date gets treated as the
range separator). It also never looked at the LLM's already-structured
`detailed_experience` output at all, so even when extraction worked
perfectly, the years stayed at 0.

This version takes the structured entries directly:
    {"designation": "...", "organization": "...", "start": "2021-01", "end": "2023-12"}
and computes years correctly, including:
    - "Present" / "Current" / "" / None  -> today
    - overlapping roles (e.g. promoted into a new title without the old
      one ending) -> Total Experience uses a *merged interval* union so
      overlap is never double-counted
    - category years (academic/industry/research/admin) are summed
      per-entry and CAN overlap each other (a "Research Professor" can
      count toward both academic and research) — that mirrors how the
      gold-standard dataset itself is structured
"""

import re
import datetime
from dateutil import parser as dateparser

TODAY = datetime.date.today()

# ---------------------------------------------------------------------------
# Designation -> category keyword maps.
# Order matters for nothing here; a single designation can match >1 bucket
# (e.g. "Research Professor" -> academic AND research), which is intentional.
# ---------------------------------------------------------------------------
ACADEMIC_KEYWORDS = [
    "professor", "lecturer", "faculty", "dean", "instructor",
    "associate professor", "assistant professor", "visiting professor",
    "adjunct", "hag", "principal",  # "Professor (HAG)" style ranks
]
INDUSTRY_KEYWORDS = [
    "engineer", "developer", "consultant", "analyst", "manager",
    "executive", "officer", "specialist", "architect", "designer",
    "associate consultant", "scientist",  # industrial R&D scientist roles
]
RESEARCH_KEYWORDS = [
    "research", "postdoc", "post-doc", "researcher", "scholar",
    "fellow", "rsearch",  # tolerate common OCR/typo variant
]
ADMIN_KEYWORDS = [
    "head", "dean", "director", "coordinator", "chair", "chairman",
    "principal investigator", "registrar", "warden", "vice chancellor",
    "hod", "in-charge", "incharge",
]


def _normalize_designation(designation: str) -> str:
    return (designation or "").lower().strip()


def _parse_month(date_str):
    """
    Parse a 'YYYY-MM', 'YYYY-MM-DD', 'Month YYYY', or bare 'YYYY' string
    into a datetime.date pinned to the first of the month.
    Returns None for "Present"/"Current"/empty/unparseable.
    """
    if not date_str:
        return None
    s = str(date_str).strip()
    if not s:
        return None
    if re.fullmatch(r"(present|current|ongoing|till date|to date|now)", s, re.I):
        return TODAY

    # Fast path: YYYY-MM or YYYY-MM-DD
    m = re.fullmatch(r"(\d{4})-(\d{1,2})(?:-\d{1,2})?", s)
    if m:
        year, month = int(m.group(1)), int(m.group(2))
        try:
            return datetime.date(year, month, 1)
        except ValueError:
            return None

    # Bare year
    m = re.fullmatch(r"\d{4}", s)
    if m:
        return datetime.date(int(s), 1, 1)

    # Fallback: let dateutil try ("January 2010", "Jan 2010", "2010/01", etc.)
    try:
        dt = dateparser.parse(s, default=datetime.datetime(1900, 1, 1))
        if dt:
            return dt.date()
    except Exception:
        pass
    return None


def _months_between(start: datetime.date, end: datetime.date) -> int:
    if not start or not end or end < start:
        return 0
    return (end.year - start.year) * 12 + (end.month - start.month)


def _classify(designation: str):
    """Return the set of category keys a designation string belongs to."""
    low = _normalize_designation(designation)
    cats = set()
    if any(k in low for k in ACADEMIC_KEYWORDS):
        cats.add("academic")
    if any(k in low for k in INDUSTRY_KEYWORDS):
        cats.add("industry")
    if any(k in low for k in RESEARCH_KEYWORDS):
        cats.add("research")
    if any(k in low for k in ADMIN_KEYWORDS):
        cats.add("admin")
    return cats


def _merge_intervals(intervals):
    """Merge overlapping/adjacent (start, end) date ranges; return total months covered."""
    cleaned = [(s, e) for s, e in intervals if s and e and e >= s]
    if not cleaned:
        return 0
    cleaned.sort(key=lambda x: x[0])
    merged = [cleaned[0]]
    for s, e in cleaned[1:]:
        last_s, last_e = merged[-1]
        if s <= last_e:  # overlap or contiguous
            merged[-1] = (last_s, max(last_e, e))
        else:
            merged.append((s, e))
    return sum(_months_between(s, e) for s, e in merged)


def parse_experience_from_entries(detailed_experience: list) -> dict:
    """
    Main entry point. Pass the structured list of experience entries,
    e.g. the `experience.detailed_experience` array already produced by
    your LLM extraction step:

        [{"designation": "Assistant Professor",
          "organization": "ABC University",
          "department": "CSE",
          "start": "2018-08",
          "end": "2020-11"}, ...]

    Returns a dict matching the gold-dataset schema:
        {
          "academic_years": float,
          "industry_years": float,
          "research_years": float,
          "administrative_years": float,
          "total_years": float,
          "current_designation": str,
          "current_organization": str,
          "current_department": str,
        }
    """
    result = {
        "academic_years": 0.0,
        "industry_years": 0.0,
        "research_years": 0.0,
        "administrative_years": 0.0,
        "total_years": 0.0,
        "current_designation": "",
        "current_organization": "",
        "current_department": "",
    }
    if not detailed_experience:
        return result

    category_months = {"academic": 0, "industry": 0, "research": 0, "admin": 0}
    all_intervals = []
    current_entry = None  # the most recent / ongoing role, for "current_*" fields

    for entry in detailed_experience:
        if not isinstance(entry, dict):
            continue
        designation = entry.get("designation", "") or ""
        start_raw = entry.get("start")
        end_raw = entry.get("end")

        start = _parse_month(start_raw)
        end_is_present = str(end_raw).strip().lower() in ("present", "current", "ongoing", "", "none", "till date", "to date", "now") or end_raw is None
        end = TODAY if end_is_present else _parse_month(end_raw)

        if start and not end:
            # unparseable end date but we have a start — skip duration but still classify
            end = None

        months = _months_between(start, end) if (start and end) else 0
        cats = _classify(designation)
        for c in cats:
            category_months[c] += months

        if start and end:
            all_intervals.append((start, end))

        # Track the most "current" role: prefer one explicitly ending in Present,
        # else fall back to the one with the latest start date.
        if end_is_present:
            if current_entry is None or (start and (current_entry[0] is None or start > current_entry[0])):
                current_entry = (start, entry)
        elif current_entry is None and start:
            if current_entry is None or start > (current_entry[0] or datetime.date.min):
                current_entry = (start, entry)

    total_months = _merge_intervals(all_intervals)

    result["academic_years"] = round(category_months["academic"] / 12, 2)
    result["industry_years"] = round(category_months["industry"] / 12, 2)
    result["research_years"] = round(category_months["research"] / 12, 2)
    result["administrative_years"] = round(category_months["admin"] / 12, 2)
    result["total_years"] = round(total_months / 12, 2)

    if current_entry:
        _, entry = current_entry
        result["current_designation"] = entry.get("designation", "") or ""
        result["current_organization"] = entry.get("organization", "") or ""
        result["current_department"] = entry.get("department", "") or ""

    return result


def parse_experience(resume_data) -> dict:
    """
    Convenience wrapper matching your original function's call shape, but
    accepting either:
      - the full parsed resume dict (with resume_data["experience"]["detailed_experience"])
      - or directly a list of detailed_experience entries

    This is the drop-in replacement for your old `parse_experience(text)`.
    Call it AFTER your LLM extraction step has produced structured JSON —
    not on raw resume text.
    """
    if isinstance(resume_data, dict):
        detailed = (
            resume_data.get("experience", {}).get("detailed_experience")
            if "experience" in resume_data
            else resume_data.get("detailed_experience", [])
        )
    elif isinstance(resume_data, list):
        detailed = resume_data
    else:
        detailed = []

    parsed = parse_experience_from_entries(detailed)

    summary = {
        "Academic Experience": parsed["academic_years"],
        "Industry Experience": parsed["industry_years"],
        "Research Experience": parsed["research_years"],
        "Administrative Experience": parsed["administrative_years"],
        "Total Experience": parsed["total_years"],
    }
    return {
        "summary": summary,
        "current_designation": parsed["current_designation"],
        "current_department": parsed["current_department"],
        "current_organization": parsed["current_organization"],
    }


if __name__ == "__main__":
    import json
    import glob
    import os

    files = glob.glob("/home/claude/gold/gold_dataset/*.json") + glob.glob("/home/claude/gold/gold_dataset/*.JSON")
    files = [f for f in files if "resume_db" not in f]  # resume_db.json is a different aggregate schema

    print(f"{'FILE':45} {'EXPECTED':>9} {'GOT':>9}  {'ACAD':>14} {'IND':>14} {'RES':>14} {'ADMIN':>14}")
    for fp in sorted(files):
        with open(fp) as f:
            data = json.load(f)
        exp = data.get("experience", {})
        detailed = exp.get("detailed_experience", [])
        if not detailed:
            continue
        got = parse_experience_from_entries(detailed)

        def fmt(exp_val, got_val):
            match = "OK" if abs((exp_val or 0) - got_val) < 0.1 else "X"
            return f"{exp_val or 0:>5}/{got_val:<5} {match}"

        print(
            f"{os.path.basename(fp)[:45]:45} "
            f"{exp.get('total_years', 0):>9} {got['total_years']:>9}  "
            f"{fmt(exp.get('academic_years'), got['academic_years']):>14} "
            f"{fmt(exp.get('industry_years'), got['industry_years']):>14} "
            f"{fmt(exp.get('research_years'), got['research_years']):>14} "
            f"{fmt(exp.get('administrative_years'), got['administrative_years']):>14}"
        )
