import re
from dateutil import parser as dateparser
from dateutil.relativedelta import relativedelta
import datetime

# Robust regular expressions for matching dates and ranges
MONTH_WORD = r'(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)'
YEAR_PATTERN = r'(?:\b(?:19|20)\d{2}\b|[\'’]?\b\d{2}\b)'
DAY_PATTERN = r'(?:\b(?:0?[1-9]|[12]\d|3[01])(?:st|nd|rd|th)?\b)'

DATE_WITH_MONTH_WORD_1 = rf'(?:{MONTH_WORD}\b[\s\.\,]*{DAY_PATTERN}?[\s\.\,\'’\-]*{YEAR_PATTERN})'
DATE_WITH_MONTH_WORD_2 = rf'(?:{DAY_PATTERN}?[\s\.\,\'’\-]*{MONTH_WORD}\b[\s\.\,\'’\-]*{YEAR_PATTERN})'
DATE_WITH_MONTH_WORD = rf'(?:{DATE_WITH_MONTH_WORD_1}|{DATE_WITH_MONTH_WORD_2})'

MONTH_NUM = r'(?:0?[1-9]|1[0-2])'
DATE_WITH_MONTH_NUM = rf'(?:{MONTH_NUM}[/\-\'’]{YEAR_PATTERN})'
DATE_YEAR_ONLY = r'(?:\b(?:19|20)\d{2}\b)'

# Add word boundary at the start to prevent matching parts of years/numbers
DATE_PATTERN = rf'\b(?:{DATE_WITH_MONTH_WORD}|{DATE_WITH_MONTH_NUM}|{DATE_YEAR_ONLY})'
PRESENT_PATTERN = r'(?:present|till\s+date|till\s+now|to\s+date|current|ongoing|now|active)'
DATE_PATTERN_END = rf'(?:{DATE_PATTERN}|(?:[\'’]?\b\d{{2}}\b)|{PRESENT_PATTERN})'

SEPARATOR_PATTERN = r'(?:\s*(?:[\-\–\—\|]|to|till|until)\s*)'
RANGE_PATTERN = re.compile(rf'({DATE_PATTERN}){SEPARATOR_PATTERN}({DATE_PATTERN_END})', re.IGNORECASE)

# Match since/from/onwards
SINCE_PATTERN = re.compile(rf'\b(?:since|from)\s+({DATE_PATTERN})|({DATE_PATTERN})\s+onwards', re.IGNORECASE)

ACADEMIC_KEYWORDS = re.compile(
    r'\b(?:professor|lecturer|teacher|teaching|faculty|instructor|tutor)\b',
    re.IGNORECASE
)
RESEARCH_KEYWORDS = re.compile(
    r'\b(?:research|postdoc|fellow|scientist|investigator|scholar|project\s+associate)\b',
    re.IGNORECASE
)
INDUSTRY_KEYWORDS = re.compile(
    r'\b(?:engineer|developer|consultant|analyst|programmer|manager|specialist|officer|administrator|corporate|company|pvt|ltd|inc|industry|industries|software|systems)\b',
    re.IGNORECASE
)
ADMIN_KEYWORDS = re.compile(
    r'\b(?:head|dean|director|coordinator|chair|principal|warden|registrar|administrative|hod)\b',
    re.IGNORECASE
)

def _resolve_2digit_year(start_year: int, end_year_str: str) -> int:
    val = int(end_year_str)
    start_century = (start_year // 100) * 100
    candidate = start_century + val
    if candidate >= start_year:
        return candidate
    candidate = start_century + 100 + val
    if abs(candidate - start_year) < 20:
        return candidate
    return val

def _normalize_and_resolve_date_string(date_str: str, ref_year: int = None) -> str:
    s = date_str.replace('’', ' ').replace("'", ' ').replace('.', ' ').strip()
    s = re.sub(r'\s+', ' ', s)
    if re.search(r'\b((?:19|20)\d{2})\b', s):
        return s
    m2 = re.findall(r'\b(\d{2})\b', s)
    if m2:
        if len(m2) >= 2:
            yy_str = m2[-1]
        else:
            yy_str = m2[0]
        yy = int(yy_str)
        if ref_year:
            yyyy = _resolve_2digit_year(ref_year, yy_str)
        else:
            if yy >= 50:
                yyyy = 1900 + yy
            else:
                yyyy = 2000 + yy
        s = re.sub(rf'\b{yy_str}\b', str(yyyy), s)
    return s

def _parse_date_with_ref(date_str: str, ref_year: int = None) -> datetime.datetime:
    date_str = date_str.strip()
    if re.search(r'(?:present|till\s+date|till\s+now|to\s+date|current|ongoing|now|active)', date_str, re.I):
        return datetime.datetime.now()
    
    normalized = _normalize_and_resolve_date_string(date_str, ref_year)
    try:
        return dateparser.parse(normalized, default=datetime.datetime(1900, 1, 1))
    except Exception:
        return None

def parse_experience(text: str) -> dict:
    summary = {
        'Academic Experience': 0.0,
        'Industry Experience': 0.0,
        'Research Experience': 0.0,
        'Administrative Experience': 0.0,
        'Total Experience': 0.0,
        'academic_years': 0.0,
        'industry_years': 0.0,
        'research_years': 0.0,
        'admin_years': 0.0,
        'total_years': 0.0
    }
    current_designation = ''
    current_department = ''
    current_organization = ''

    if not text:
        res = {
            'summary': summary,
            'current_designation': current_designation,
            'current_department': current_department,
            'current_organization': current_organization
        }
        for k in ['current_designation', 'current_department', 'current_organization', 
                  'designation', 'department', 'organization', 
                  'Current Designation', 'Current Department', 'Current Organization']:
            summary[k] = ''
        return res

    raw_lines = [l.strip() for l in text.splitlines() if l.strip()]
    
    # Merge wrapped lines
    lines = []
    for line in raw_lines:
        if not lines:
            lines.append(line)
            continue
        is_bullet = (
            line.startswith(('●', '❖', '*', '-', '▪', '•', '', '✔', '▪', '■', '✦', '★')) or
            re.match(r'^\d+[\.\)\-]', line) or
            re.match(r'^\uf0d8', line)
        )
        is_continuation = not is_bullet and (
            line[0].islower() or
            re.match(r'^\d+\s*(?:months?|years?)\b', line, re.I) or
            re.match(r'^(?:19|20)\d{2}\b', line)
        )
        if is_continuation:
            lines[-1] = lines[-1] + " " + line
        else:
            lines.append(line)

    # Process lines to find date ranges and extract durations
    jobs = []
    for i, line in enumerate(lines):
        # Extract ranges and replace them in the line for since matching
        ranges = []
        remaining_line = line
        for m in RANGE_PATTERN.finditer(line):
            ranges.append((m.group(1), m.group(2)))
            remaining_line = remaining_line.replace(m.group(0), ' ')
            
        since_matches = SINCE_PATTERN.findall(remaining_line)
        for match1, match2 in since_matches:
            start_str = match1 if match1 else match2
            ranges.append((start_str, 'Present'))
                    
        if ranges:
            for start_str, end_str in ranges:
                start_year_match = re.search(r'\b((?:19|20)\d{2})\b', start_str)
                ref_year = None
                if start_year_match:
                    ref_year = int(start_year_match.group(1))
                else:
                    m2_start = re.search(r'\b(\d{2})\b', start_str)
                    if m2_start:
                        yy = int(m2_start.group(1))
                        ref_year = 1900 + yy if yy >= 50 else 2000 + yy
                
                d1 = _parse_date_with_ref(start_str)
                d2 = _parse_date_with_ref(end_str, ref_year)
                
                if d1 and d2:
                    rd = relativedelta(d2, d1)
                    months = rd.years * 12 + rd.months
                    duration = max(0.0, months / 12.0)
                    
                    context_lines = []
                    if i - 2 >= 0:
                        context_lines.append(lines[i-2])
                    if i - 1 >= 0:
                        context_lines.append(lines[i-1])
                    context_lines.append(line)
                    
                    if i + 1 < len(lines):
                        next_line = lines[i+1].strip()
                        is_new_item = (
                            next_line.startswith(('●', '❖', '*', '-', '▪', '•')) or
                            re.match(r'^\d+[\.\)\-]', next_line)
                        )
                        if not is_new_item and not RANGE_PATTERN.search(next_line):
                            context_lines.append(lines[i+1])
                        
                    context_text = " | ".join(context_lines)
                    
                    jobs.append({
                        'start_date': d1,
                        'end_date': d2,
                        'duration': duration,
                        'context': context_text,
                        'line': line
                    })

    # Classify each job individually and sum up durations
    academic_total = 0.0
    industry_total = 0.0
    research_total = 0.0
    admin_total = 0.0

    intervals = []
    
    for job in jobs:
        low_context = job['context'].lower()
        
        is_academic = bool(ACADEMIC_KEYWORDS.search(low_context))
        is_research = bool(RESEARCH_KEYWORDS.search(low_context))
        is_industry = bool(INDUSTRY_KEYWORDS.search(low_context))
        is_admin = bool(ADMIN_KEYWORDS.search(low_context))
        
        if is_industry:
            if is_academic or is_research:
                if not re.search(r'\b(?:pvt|ltd|inc|company|corporation|industry|industries)\b', low_context):
                    is_industry = False
            
        if not (is_academic or is_research or is_industry or is_admin):
            is_academic = True
            
        if is_academic:
            academic_total += job['duration']
        if is_industry:
            industry_total += job['duration']
        if is_research:
            research_total += job['duration']
        if is_admin:
            admin_total += job['duration']
            
        intervals.append((job['start_date'], job['end_date']))

    # Compute non-overlapping total experience
    intervals.sort(key=lambda x: x[0])
    merged_intervals = []
    for start, end in intervals:
        if not merged_intervals:
            merged_intervals.append((start, end))
        else:
            prev_start, prev_end = merged_intervals[-1]
            if start <= prev_end:
                merged_intervals[-1] = (prev_start, max(prev_end, end))
            else:
                merged_intervals.append((start, end))
                
    total_months = 0
    for start, end in merged_intervals:
        rd = relativedelta(end, start)
        months = rd.years * 12 + rd.months
        total_months += max(0, months)
    total_total = total_months / 12.0

    summary['Academic Experience'] = round(academic_total, 2)
    summary['Industry Experience'] = round(industry_total, 2)
    summary['Research Experience'] = round(research_total, 2)
    summary['Administrative Experience'] = round(admin_total, 2)
    summary['Total Experience'] = round(total_total, 2)

    summary['academic_years'] = summary['Academic Experience']
    summary['industry_years'] = summary['Industry Experience']
    summary['research_years'] = summary['Research Experience']
    summary['admin_years'] = summary['Administrative Experience']
    summary['total_years'] = summary['Total Experience']

    # Extract current designation, organization, department
    if lines:
        target_line = None
        for l in lines[:3]:
            if len(l.strip()) > 5 and any(c.isalpha() for c in l):
                target_line = l.strip()
                break
        if not target_line:
            target_line = lines[0]
            
        if target_line:
            if ',' in target_line:
                parts = [p.strip() for p in target_line.split(',')]
                current_designation = parts[0]
                for part in parts[1:]:
                    low_p = part.lower()
                    if 'department' in low_p or 'dept' in low_p:
                        current_department = part
                current_organization = parts[-1]
                if current_organization == current_department and len(parts) > 2:
                    current_organization = parts[-2]
            else:
                if ' at ' in target_line:
                    parts = target_line.split(' at ')
                    current_designation = parts[0].strip()
                    current_organization = parts[1].strip()
                else:
                    current_designation = target_line.strip()

    current_designation = current_designation.strip()
    current_department = current_department.strip()
    current_organization = current_organization.strip()

    res = {
        'summary': summary,
        'current_designation': current_designation,
        'current_department': current_department,
        'current_organization': current_organization
    }

    for k in ['current_designation', 'current_department', 'current_organization', 
              'designation', 'department', 'organization', 
              'Current Designation', 'Current Department', 'Current Organization']:
        norm_key = k.lower().replace(' ', '_')
        if 'designation' in norm_key:
            summary[k] = current_designation
        elif 'department' in norm_key:
            summary[k] = current_department
        elif 'organization' in norm_key:
            summary[k] = current_organization

    return res
