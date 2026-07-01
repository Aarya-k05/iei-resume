import json
import os
from pathlib import Path
from typing import Dict, List, Tuple, Any
import pandas as pd
from difflib import SequenceMatcher
from io import BytesIO


def normalize_string(s: str) -> str:
    """Normalize string for comparison: lowercase, strip whitespace."""
    if not isinstance(s, str):
        s = str(s) if s is not None else ''
    return s.lower().strip()


def string_similarity(a: str, b: str) -> float:
    """Calculate string similarity score (0.0 to 1.0)."""
    a = normalize_string(a)
    b = normalize_string(b)
    if not a or not b:
        return 1.0 if a == b else 0.0
    return SequenceMatcher(None, a, b).ratio()


def compare_personal(extracted: Dict, golden: Dict) -> Tuple[Dict[str, float], List[Dict]]:
    """Compare personal information."""
    scores = {}
    failures = []

    fields = ['name', 'email', 'phone', 'designation', 'department', 'organization']

    for field in fields:
        ext_val = normalize_string(extracted.get(field, ''))
        gold_val = normalize_string(golden.get(field, ''))

        if not gold_val:  # Skip if golden value is empty
            scores[f'personal_{field}'] = 1.0
            continue

        sim = string_similarity(ext_val, gold_val)
        scores[f'personal_{field}'] = sim

        if sim < 0.9:  # Threshold for failure
            failures.append({
                'field': f'Personal: {field.title()}',
                'expected': gold_val,
                'extracted': ext_val
            })

    return scores, failures


def compare_education(extracted: List, golden: List) -> Tuple[Dict[str, float], List[Dict]]:
    """Compare education information."""
    scores = {}
    failures = []

    # Extract degrees from both
    ext_degrees = {e.get('degree', 'Unknown').upper() for e in extracted if e}
    gold_degrees = {e.get('degree', 'Unknown').upper() for e in golden if e}

    # Simplify degree comparison: UG, PG, PhD
    def get_degree_type(deg_str):
        deg = deg_str.upper()
        if 'PHDR' in deg or 'DOCTORAL' in deg or 'PH.D' in deg:
            return 'PhD'
        elif 'MASTER' in deg or 'M.SC' in deg or 'M.A' in deg:
            return 'PG'
        elif 'BACHELOR' in deg or 'B.SC' in deg or 'B.A' in deg or 'B.TECH' in deg:
            return 'UG'
        return 'Other'

    ext_types = {get_degree_type(d) for d in ext_degrees}
    gold_types = {get_degree_type(d) for d in gold_degrees}

    # Score education completeness
    if 'PhD' in gold_types:
        scores['education_phd'] = 1.0 if 'PhD' in ext_types else 0.0
        if 'PhD' not in ext_types:
            failures.append({
                'field': 'Education: PhD',
                'expected': 'Present',
                'extracted': 'Not found'
            })

    if 'PG' in gold_types:
        scores['education_pg'] = 1.0 if 'PG' in ext_types else 0.0
        if 'PG' not in ext_types:
            failures.append({
                'field': 'Education: PG',
                'expected': 'Present',
                'extracted': 'Not found'
            })

    if 'UG' in gold_types:
        scores['education_ug'] = 1.0 if 'UG' in ext_types else 0.0
        if 'UG' not in ext_types:
            failures.append({
                'field': 'Education: UG',
                'expected': 'Present',
                'extracted': 'Not found'
            })

    # Default to 1.0 for each if not scored yet
    for key in ['education_phd', 'education_pg', 'education_ug']:
        if key not in scores:
            scores[key] = 1.0

    return scores, failures


def compare_experience(extracted: Dict, golden: Dict) -> Tuple[Dict[str, float], List[Dict]]:
    """Compare experience information."""
    scores = {}
    failures = []

    # Extract experience counts from extracted dict
    exp_summary = extracted.get('summary', {})

    fields_to_compare = [
        ('academic_years', 'Academic Experience'),
        ('industry_years', 'Industry Experience'),
        ('research_years', 'Research Experience'),
        ('admin_years', 'Administrative Experience'),
        ('total_years', 'Total Experience'),
    ]

    for ext_field, label in fields_to_compare:
        ext_val = exp_summary.get(ext_field, 0)
        gold_val = golden.get(ext_field, golden.get('experience', {}).get(ext_field, 0))

        if not gold_val:
            scores[f'experience_{ext_field}'] = 1.0
            continue

        # Allow 10% tolerance for numeric comparison
        if isinstance(ext_val, (int, float)) and isinstance(gold_val, (int, float)):
            diff = abs(ext_val - gold_val)
            max_val = max(abs(gold_val), 1.0)
            sim = max(0.0, 1.0 - (diff / max_val))
            scores[f'experience_{ext_field}'] = min(1.0, sim + 0.1)  # Add tolerance

            if sim < 0.8:
                failures.append({
                    'field': f'Experience: {label}',
                    'expected': str(gold_val),
                    'extracted': str(ext_val)
                })

    return scores, failures


def compare_publications(extracted: Dict, golden: Dict) -> Tuple[Dict[str, float], List[Dict]]:
    """Compare publication counts."""
    scores = {}
    failures = []

    counts = extracted.get('counts', {})

    pub_fields = [
        ('journal', 'Journal Count'),
        ('int_conf', 'Conference Count'),
        ('book', 'Book Count'),
        ('book_chapter', 'Book Chapter Count'),
        ('patent', 'Patent Count'),
    ]

    for ext_field, label in pub_fields:
        ext_val = counts.get(ext_field, 0)
        gold_val = golden.get(ext_field, 0) if isinstance(golden, dict) else 0

        if ext_field == 'int_conf':
            gold_val = golden.get('conference_count', 0) if isinstance(golden, dict) else 0

        if not gold_val:
            scores[f'publications_{ext_field}'] = 1.0
            continue

        # Allow 20% tolerance for publication counts (often approximate)
        if isinstance(ext_val, (int, float)) and isinstance(gold_val, (int, float)):
            diff = abs(ext_val - gold_val)
            max_val = max(gold_val, 1)
            sim = max(0.0, 1.0 - (diff / max_val))
            scores[f'publications_{ext_field}'] = min(1.0, sim + 0.2)

            if sim < 0.6:
                failures.append({
                    'field': f'Publications: {label}',
                    'expected': str(int(gold_val)),
                    'extracted': str(int(ext_val))
                })

    return scores, failures


def evaluate_resume(pdf_path: str, extracted_data: Dict, golden_path: str) -> Dict:
    """Evaluate a single resume against golden data."""

    # Load golden JSON
    with open(golden_path, 'r', encoding='utf-8') as f:
        golden_data = json.load(f)

    all_scores = {}
    all_failures = []

    # Compare personal info
    ext_personal = extracted_data.get('personal', {}) if isinstance(extracted_data, dict) else {}
    gold_personal = golden_data.get('personal', {})
    pers_scores, pers_failures = compare_personal(ext_personal, gold_personal)
    all_scores.update(pers_scores)
    all_failures.extend(pers_failures)

    # Compare education
    ext_edu = extracted_data.get('education', []) if isinstance(extracted_data.get('education'), list) else []
    gold_edu = golden_data.get('education', [])
    edu_scores, edu_failures = compare_education(ext_edu, gold_edu)
    all_scores.update(edu_scores)
    all_failures.extend(edu_failures)

    # Compare experience
    ext_exp = extracted_data.get('experience', {}) if isinstance(extracted_data.get('experience'), dict) else {}
    gold_exp = golden_data.get('experience', {})
    exp_scores, exp_failures = compare_experience(ext_exp, gold_exp)
    all_scores.update(exp_scores)
    all_failures.extend(exp_failures)

    # Compare publications
    ext_pubs = extracted_data.get('publications', {}) if isinstance(extracted_data.get('publications'), dict) else {}
    gold_pubs = golden_data.get('publications', {})
    pub_scores, pub_failures = compare_publications(ext_pubs, gold_pubs)
    all_scores.update(pub_scores)
    all_failures.extend(pub_failures)

    # Calculate category averages
    personal_scores = [v for k, v in all_scores.items() if k.startswith('personal_')]
    education_scores = [v for k, v in all_scores.items() if k.startswith('education_')]
    experience_scores = [v for k, v in all_scores.items() if k.startswith('experience_')]
    publication_scores = [v for k, v in all_scores.items() if k.startswith('publications_')]

    result = {
        'resume_name': Path(pdf_path).stem,
        'overall_accuracy': sum(all_scores.values()) / len(all_scores) if all_scores else 0.0,
        'personal_accuracy': sum(personal_scores) / len(personal_scores) if personal_scores else 1.0,
        'education_accuracy': sum(education_scores) / len(education_scores) if education_scores else 1.0,
        'experience_accuracy': sum(experience_scores) / len(experience_scores) if experience_scores else 1.0,
        'publication_accuracy': sum(publication_scores) / len(publication_scores) if publication_scores else 1.0,
        'failed_fields_count': len(all_failures),
        'failed_fields': ' | '.join([f['field'] for f in all_failures]) if all_failures else 'None',
        'failures': all_failures,
    }

    return result


def run_evaluation(gold_dataset_path: str) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Run evaluation on all resumes in gold dataset."""

    dataset_path = Path(gold_dataset_path)
    if not dataset_path.exists():
        return pd.DataFrame(), pd.DataFrame()

    # Find all PDF files
    pdf_files = sorted(dataset_path.glob('*.pdf'))

    evaluation_results = []
    all_failures = []

    for pdf_file in pdf_files:
        # Find corresponding JSON
        json_candidates = list(dataset_path.glob(f'{pdf_file.stem}.*json'))
        if not json_candidates:
            continue

        json_file = json_candidates[0]

        try:
            # For now, create a placeholder result (in production, would call extraction pipeline)
            # This is where you'd integrate with the actual extraction pipeline
            from extractor.text_extractor import extract_text_from_file
            from section_detector.detector import detect_sections
            from parsers.education_parser import parse_education
            from parsers.experience_parser import parse_experience
            from parsers.publication_parser import parse_publications
            from utils.helpers import extract_email, extract_phone, extract_name

            text = extract_text_from_file(str(pdf_file))
            if not text:
                continue

            sections = detect_sections(text)

            # --- Bug #2 fix: parse experience exactly once and reuse the result ---
            exp = parse_experience(sections.get('experience', ''), full_text=text)
            summary = exp.get('summary', {})

            # --- Bug #3 fix: don't trust one key spelling. Try the common
            # variants a parser might actually use, in order of likelihood.
            # Once you paste parsers/experience_parser.py I'll collapse this
            # back down to the single correct key.
            def first_present(d: Dict, *keys, default=''):
                for k in keys:
                    if d.get(k):
                        return d.get(k)
                return default

            designation = first_present(
                summary, 'current_designation', 'designation', 'Current Designation'
            )
            department = first_present(
                summary, 'current_department', 'department', 'Current Department'
            )
            organization = first_present(
                summary, 'current_organization', 'organization', 'Current Organization'
            )

            # --- Bug #1 fix: build education_list as a separate statement,
            # not as a key/value pair inside the extracted_data dict literal ---
            edu = parse_education(sections.get('education', ''))

            education_list = []

            if edu.get('ug_degree'):
                education_list.append({'degree': edu['ug_degree']})

            if edu.get('pg_degree'):
                education_list.append({'degree': edu['pg_degree']})

            if edu.get('phd_university'):
                education_list.append({'degree': 'PhD'})

            extracted_name_val = extract_name(text)
            extracted_data = {
                'personal': {
                    'name': extracted_name_val,
                    'email': extract_email(text, name=extracted_name_val),
                    'phone': extract_phone(text),
                    'designation': designation,
                    'department': department,
                    'organization': organization,
                },
                'education': education_list,
                'experience': exp,
                'publications': parse_publications(sections.get('publications', '')),
            }

            result = evaluate_resume(str(pdf_file), extracted_data, str(json_file))
            evaluation_results.append(result)
            all_failures.extend([(pdf_file.stem, f) for f in result.get('failures', [])])

        except Exception as e:
            print(f"Error evaluating {pdf_file}: {e}")
            continue

    # Create evaluation report DataFrame
    report_data = []
    for res in evaluation_results:
        report_data.append({
            'Resume Name': res['resume_name'],
            'Overall Accuracy': f"{res['overall_accuracy']*100:.1f}%",
            'Personal Accuracy': f"{res['personal_accuracy']*100:.1f}%",
            'Education Accuracy': f"{res['education_accuracy']*100:.1f}%",
            'Experience Accuracy': f"{res['experience_accuracy']*100:.1f}%",
            'Publication Accuracy': f"{res['publication_accuracy']*100:.1f}%",
            'Failed Fields Count': res['failed_fields_count'],
            'Failed Fields': res['failed_fields'],
        })

    eval_df = pd.DataFrame(report_data)

    # Create failed fields DataFrame
    failures_data = []
    for resume_name, failure in all_failures:
        failures_data.append({
            'Resume': resume_name,
            'Field': failure['field'],
            'Expected Value': failure['expected'],
            'Extracted Value': failure['extracted'],
        })

    failures_df = pd.DataFrame(failures_data)

    return eval_df, failures_df