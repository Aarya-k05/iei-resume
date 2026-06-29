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

DATE_NUMERIC_3_PARTS = r'(?:\b\d{1,2}[/\-\. \t]+[0-1]?\d[/\-\. \t]+(?:(?:19|20)?\d{2})\b)'

DATE_PATTERN = rf'\b(?:{DATE_NUMERIC_3_PARTS}|{DATE_WITH_MONTH_WORD}|{DATE_WITH_MONTH_NUM}|{DATE_YEAR_ONLY})'
PRESENT_PATTERN = r'(?:present|till\s+date|till\s+now|to\s+date|current|ongoing|now|active)'
DATE_PATTERN_END = rf'(?:{DATE_PATTERN}|(?:[\'’]?\b\d{{2}}\b(?![\/\-\.]\d))|{PRESENT_PATTERN})'

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

DESIGNATION_KEYWORDS = re.compile(
    r'\b(?:professor|lecturer|scientist|dean|director|head|associate\s+professor|assistant\s+professor|asst\s+professor|asst\.\s+professor|sr\.asst\s+professor|reader|member\s+technical\s+staff|consultant)\b',
    re.IGNORECASE
)

DEPT_KEYWORDS = re.compile(
    r'\b(?:department|dept|school|centre|center|discipline)\s+of\b|\b(?:department|dept|school|centre|center|discipline)\b',
    re.IGNORECASE
)

ORG_KEYWORDS = re.compile(
    r'\b(?:institute|university|college|drdo|c\-ac|organisation|organization|iit|nit|iiit|bits|fcrit|nitt|government\s+college|sathyabama|jerusalem)\b',
    re.IGNORECASE
)

DESIGNATION_CLEAN_RE = re.compile(
    r'\b(?:senior|junior|assistant|associate|asst\.?|sr\.?|sr\.asst|adjunct|visiting|hag|head|dean|director|chair|principal|warden|registrar|hag\s+scale)?\s*(?:professor|lecturer|scientist|reader|member\s+technical\s+staff|consultant|dean|director|head|mts|hod|h\.o\.d\.)\b',
    re.IGNORECASE
)

BLACKLIST = re.compile(
    r'\b(?:position|post|apply|application|faculty|curriculum|vitae|resume|biodata|profile|cv|objective|career|address|contact|email|phone|mobile|website|personal|details|hobbies|languages|skills|matric|sec\.school|secondary|hr\.sec|society|growth|potential)\b',
    re.IGNORECASE
)

def extract_personal_meta(text: str, exp_text: str) -> tuple:
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    top_lines = [l for l in lines[:20] if not BLACKLIST.search(l)]
    
    designation = ""
    department = ""
    organization = ""
    
    def clean_val(val: str) -> str:
        val = re.sub(r'^[•\-\*●❖\uf0d8\s_·]+', '', val)
        val = re.sub(r'^(?:working\s+as\s+|worked\s+as\s+|presently\s+holding\s+the\s+charge\s+of\s+|presently\s+|holding\s+the\s+charge\s+of\s+)', '', val, flags=re.I)
        return val.strip()

    def clean_designation(line: str) -> str:
        m = DESIGNATION_CLEAN_RE.findall(line)
        if m:
            return ' & '.join([x.strip() for x in m if x.strip()])
        return clean_val(line)

    def split_and_extract_meta(line: str) -> tuple:
        line = clean_val(line)
        # Strip dates
        line = re.sub(r'\b(?:from|during|since)\b.*$', '', line, flags=re.I).strip()
        line = re.sub(r'[\d/\-\.\s]+to[\d/\-\.\s]+$', '', line, flags=re.I).strip()
        line = re.sub(r'\b(?:19|20)\d{2}\b.*$', '', line).strip()
        line = re.sub(r'[,.\s\-–—/]+$', '', line).strip()
        
        des = ""
        dept = ""
        org = ""
        
        comma_parts = [p.strip() for p in re.split(r'[,|–\-]', line) if p.strip()]
        if len(comma_parts) >= 2:
            for part in comma_parts:
                part_clean = clean_val(part)
                if DESIGNATION_KEYWORDS.search(part_clean) and not des:
                    des = part_clean
                elif DEPT_KEYWORDS.search(part_clean) and not dept:
                    dept = part_clean
                elif ORG_KEYWORDS.search(part_clean) and not org:
                    org = part_clean
                    
            used = [des, dept, org]
            remaining = [p.strip() for p in comma_parts if clean_val(p) not in used]
            for part in remaining:
                if not des:
                    des = part
                elif not dept and DEPT_KEYWORDS.search(part):
                    dept = part
                elif not org:
                    org = part
                    
        if not org or not dept:
            parts = re.split(r'\b(?:at|in|with|for)\b', line, maxsplit=1, flags=re.I)
            if len(parts) == 2:
                des_part = parts[0].strip()
                org_part = parts[1].strip()
                
                if not des:
                    if " of " in des_part.lower():
                        des_sub = re.split(r'\bof\b', des_part, maxsplit=1, flags=re.I)
                        des = des_sub[0].strip()
                        if not dept:
                            dept = des_sub[1].strip()
                    else:
                        des = des_part
                elif " of " in des_part.lower() and not dept:
                    des_sub = re.split(r'\bof\b', des_part, maxsplit=1, flags=re.I)
                    dept = des_sub[1].strip()
                    
                if not org:
                    org = org_part
                    
        return clean_val(des), clean_val(dept), clean_val(org)

    # 1. Try to find the current job details from top lines
    for line in top_lines:
        line_clean = clean_val(line)
        if DESIGNATION_KEYWORDS.search(line_clean):
            if ORG_KEYWORDS.search(line_clean) or DEPT_KEYWORDS.search(line_clean):
                des, dept, org = split_and_extract_meta(line)
                if des: designation = clean_designation(des)
                if dept: department = dept
                if org: organization = org
                if designation and (department or organization):
                    break
            else:
                parts = [p.strip() for p in re.split(r'[,|–\-]', line_clean)]
                for part in parts:
                    if DESIGNATION_KEYWORDS.search(part):
                        designation = clean_designation(part)
                        break
                if designation:
                    break

    # 2. Try to find department/organization in top lines if not found
    if not department:
        for line in top_lines:
            line_clean = clean_val(line)
            if DEPT_KEYWORDS.search(line_clean) and not DESIGNATION_KEYWORDS.search(line_clean):
                department = line_clean
                break
    if not organization:
        for line in top_lines:
            line_clean = clean_val(line)
            if ORG_KEYWORDS.search(line_clean) and not DESIGNATION_KEYWORDS.search(line_clean):
                organization = line_clean
                break

    # 3. Fallback to experience text first items (most recent job!)
    if (not designation or not organization) and exp_text:
        exp_lines = [l.strip() for l in exp_text.splitlines() if l.strip()]
        for line in exp_lines[:4]:
            if BLACKLIST.search(line):
                continue
            line_clean = clean_val(line)
            if DESIGNATION_KEYWORDS.search(line_clean):
                des, dept, org = split_and_extract_meta(line)
                if not designation and des:
                    designation = clean_designation(des)
                if not department and dept:
                    department = dept
                if not organization and org:
                    organization = org
                if designation and organization:
                    break

    # Final cleanup
    if designation: designation = clean_designation(designation)
    if department: department = clean_val(department)
    if organization: organization = clean_val(organization)
    
    return designation, department, organization

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
        return dateparser.parse(normalized, dayfirst=True, default=datetime.datetime(1900, 1, 1))
    except Exception:
        return None

def parse_experience(text: str, full_text: str = "") -> dict:
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
    
    current_designation, current_department, current_organization = extract_personal_meta(
        full_text if full_text else text,
        text
    )

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
            summary[k] = current_designation if 'designation' in k.lower() else (current_department if 'department' in k.lower() else current_organization)
        return res

    if text:
        text = re.sub(r'\b(to|till|until|from|since|and)(\d)', r'\1 \2', text, flags=re.I)
    raw_lines = [l.strip() for l in text.splitlines() if l.strip()]
    
    # Merge wrapped lines
    lines = []
    for line in raw_lines:
        if not lines:
            lines.append(line)
            continue
        is_bullet = (
            line.startswith(('●', '❖', '*', '-', '▪', '•', '', '✔', '▪', '■', '✦', '★', '·', '', '\uf0b7', '\uf0b8', '\u2022')) or
            re.match(r'^\d+[\.\)\-]', line) or
            re.match(r'^\uf0d8', line) or
            re.match(r'^(?:worked|working|associated|served|employed|appointed|visiting|assistant|associate|professor|lecturer|teacher)\b', line, re.I)
        )
        is_continuation = not is_bullet
        if is_continuation:
            lines[-1] = lines[-1] + " " + line
        else:
            lines.append(line)

    # Process lines to find date ranges and extract durations
    jobs = []
    for i, line in enumerate(lines):
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

    academic_intervals = []
    industry_intervals = []
    research_intervals = []
    admin_intervals = []
    total_intervals = []
    
    for job in jobs:
        low_context = job['context'].lower()
        
        is_academic = bool(ACADEMIC_KEYWORDS.search(low_context))
        is_industry = bool(INDUSTRY_KEYWORDS.search(low_context))
        is_research = bool(RESEARCH_KEYWORDS.search(low_context))
        is_admin = bool(ADMIN_KEYWORDS.search(low_context))
        
        # Avoid treating administrative academic placement/systems jobs as industry
        is_academic_org = bool(re.search(r'\b(?:university|univ|college|institute|iit|nit|iiit|bits|school|board|convent|academy)\b', low_context))
        if is_industry and is_academic_org:
            if not re.search(r'\b(?:pvt|ltd|inc|company|corporation|industry|industries|corp\b|co\b)\b', low_context):
                is_industry = False
                
        if is_industry:
            if is_academic or is_research:
                if not re.search(r'\b(?:pvt|ltd|inc|company|corporation|industry|industries)\b', low_context):
                    is_industry = False
            
        if not (is_academic or is_research or is_industry or is_admin):
            is_academic = True
            
        if is_academic:
            academic_intervals.append((job['start_date'], job['end_date']))
        if is_industry:
            industry_intervals.append((job['start_date'], job['end_date']))
        if is_research:
            research_intervals.append((job['start_date'], job['end_date']))
        if is_admin:
            admin_intervals.append((job['start_date'], job['end_date']))
            
        total_intervals.append((job['start_date'], job['end_date']))

    def _compute_deduplicated_duration(intervals_list):
        if not intervals_list:
            return 0.0
        # Make a copy so we don't mutate original intervals list
        intervals_copy = list(intervals_list)
        intervals_copy.sort(key=lambda x: x[0])
        merged_intervals = []
        for start, end in intervals_copy:
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
        return round(total_months / 12.0, 2)

    summary['Academic Experience'] = _compute_deduplicated_duration(academic_intervals)
    summary['Industry Experience'] = _compute_deduplicated_duration(industry_intervals)
    summary['Research Experience'] = _compute_deduplicated_duration(research_intervals)
    summary['Administrative Experience'] = _compute_deduplicated_duration(admin_intervals)
    summary['Total Experience'] = _compute_deduplicated_duration(total_intervals)

    summary['academic_years'] = summary['Academic Experience']
    summary['industry_years'] = summary['Industry Experience']
    summary['research_years'] = summary['Research Experience']
    summary['admin_years'] = summary['Administrative Experience']
    summary['total_years'] = summary['Total Experience']

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
