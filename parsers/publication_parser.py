import re

YEAR_RE = re.compile(r'(19|20)\d{2}')

# Patterns for detecting numbered or bulleted publication entries
ENTRY_START_RE = re.compile(r'^\d{1,2}[\).\-](?:\s+|$)')
BULLET_START_RE = re.compile(r'^[\u2022\-\*](?:\s+|$)')

# Patterns for extracting metadata from a publication string
IMPACT_FACTOR_RE = re.compile(r'impact\s*factor[:\s]*([0-9]+(?:\.[0-9]+)?)', re.IGNORECASE)
SCOPUS_RE = re.compile(r'scopus', re.IGNORECASE)
ISSN_RE = re.compile(r'ISSN[:\s]*[\dX\-]+', re.IGNORECASE)
DOI_RE = re.compile(r'doi[:\s]*\S+', re.IGNORECASE)

# Count keywords explicitly stated in the resume (e.g. "10 Journal papers")
COUNT_PATTERNS = {
    'journal': re.compile(r'(\d+)\s+journal', re.IGNORECASE),
    'int_conf': re.compile(r'(\d+)\s+international\s+conference', re.IGNORECASE),
    'nat_conf': re.compile(r'(\d+)\s+national\s+conference', re.IGNORECASE),
    'book': re.compile(r'(\d+)\s+book(?!\s+chapter)', re.IGNORECASE),
    'book_chapter': re.compile(r'(\d+)\s+book\s+chapter', re.IGNORECASE),
    'patent': re.compile(r'(\d+)\s+patent', re.IGNORECASE),
}

# Keywords that indicate an entry is NOT a publication (administrative/committee roles)
NON_PUBLICATION_KEYWORDS = [
    "coordinator",
    "co-ordinator",
    "committee",
    "member of",
    "bos",
    "evaluator",
    "judge",
    "judged",
    "moderator",
    "moderation",
    "syllabus",
    "toycathon",
    "responsibilities",
    "administrative",
    "exam",
    "convener",
    "faculty advisor",
    "coordinator of",
    "attended",
    "participated",
    "worked as",
    "working as",
    "project description",
    "team functionality",
    "hereby declare",
    "declaration",
    "place:",
    "date:",
]

# At least one of these must be present for an entry to be accepted as a publication
PUBLICATION_INDICATORS = [
    "journal",
    "conference",
    "proceedings",
    "ieee",
    "springer",
    "elsevier",
    "wiley",
    "taylor",
    "scopus",
    "doi",
    "issn",
    "isbn",
    "international journal",
    "transactions",
    "patent",
    "book chapter",
]


def _is_valid_publication(entry: str) -> bool:
    entry_lower = entry.lower()

    if any(kw in entry_lower for kw in NON_PUBLICATION_KEYWORDS):
        return False

    if any(ind in entry_lower for ind in PUBLICATION_INDICATORS):
        return True

    has_year = bool(YEAR_RE.search(entry))
    has_enough_words = len(entry.split()) > 7
    return has_year and has_enough_words


def _classify(entry: str) -> str:
    low = entry.lower()
    if 'patent' in low:
        return 'Patent'
    if 'book chapter' in low:
        return 'Book Chapter'
    if 'book' in low and 'chapter' not in low:
        return 'Book'
    if 'conference' in low or 'proceedings' in low or 'proc.' in low:
        return 'International Conference' if 'international' in low else 'National Conference'
    return 'Journal'


def _split_title_venue(entry: str):
    cleaned = re.sub(r'^[\d]+[\).\-]\s+', '', entry).strip()
    cleaned = re.sub(r'^[\u2022\-\*]\s+', '', cleaned).strip()

    # Check for quotes: “...”, "...", ‘...’, '...'
    quote_match = re.search(r'[“"‘\'](.*?)[”"’\']', cleaned)
    if quote_match:
        title = quote_match.group(1).strip()
        remaining = cleaned[quote_match.end():].strip()
        remaining = re.sub(r'^[,.\s\-–—/]+', '', remaining).strip()
        remaining = re.sub(r'^(?:in|at|published in|published at)\s+', '', remaining, flags=re.I).strip()
        return title, remaining

    # Fallback to standard split patterns
    for pattern in [r'\s+-\s+', r'\s+–\s+', r'\s+,\s+', r'\s+in\s+(?=[A-Z])', r'\s+In\s+']:
        parts = re.split(pattern, cleaned, maxsplit=1)
        if len(parts) == 2 and len(parts[0].split()) >= 3:
            return parts[0].strip(), parts[1].strip()

    return cleaned, ''


def _extract_journal_details(entry: str) -> dict:
    title, venue = _split_title_venue(entry)

    if_match = IMPACT_FACTOR_RE.search(entry)
    impact_factor = if_match.group(1) if if_match else 'N/A'

    scopus_indexed = 'Yes' if SCOPUS_RE.search(entry) else 'Unknown'

    details_parts = []
    issn = ISSN_RE.search(entry)
    if issn:
        details_parts.append(issn.group(0))
    doi = DOI_RE.search(entry)
    if doi:
        details_parts.append(doi.group(0))
    vol_match = re.search(r'[Vv]ol\.?\s*\d+.*?(?:pp?\.?\s*[\d\-]+)?', entry)
    if vol_match:
        details_parts.append(vol_match.group(0).strip())

    journal_details = ', '.join(details_parts) if details_parts else venue

    return {
        'journal_name': venue,
        'journal_details': journal_details,
        'impact_factor': impact_factor,
        'scopus_indexed': scopus_indexed,
    }


def _extract_conference_details(entry: str) -> dict:
    _, venue = _split_title_venue(entry)
    return {'conference_name': venue}


def _group_entries(lines: list) -> list:
    buffer = []
    entries = []

    for line in lines:
        starts_continuation = bool(re.match(r'^(?:vol|volume|issue|no\.?|pp\.?|p\.?|page|pages|issn|isbn|doi|https?:\/\/|www\.)|^\d+\s*,\s*|^\d+\s*$', line, re.I))
        is_new = (
            not starts_continuation and (
                ENTRY_START_RE.match(line)
                or BULLET_START_RE.match(line)
                or (YEAR_RE.search(line) and len(line.split()) > 5)
            )
        )
        if is_new:
            if buffer:
                entries.append(' '.join(buffer))
            buffer = [line]
        else:
            if buffer:
                buffer.append(line)
            elif len(line.split()) > 6:
                buffer = [line]

    if buffer:
        entries.append(' '.join(buffer))

    return entries


def parse_publications(text: str) -> dict:
    if not text:
        return {'counts': {}, 'publications': []}

    # Clean zero-width space and other zero-width characters
    text = text.replace('\u200b', '').replace('\u200c', '').replace('\u200d', '').replace('\u200e', '').replace('\u200f', '').replace('\ufeff', '')

    counts = {
        'journal': 0, 'int_conf': 0, 'nat_conf': 0,
        'book': 0, 'book_chapter': 0, 'patent': 0,
    }

    # Extract explicit summary counts from the text block
    explicit_counts = {
        'journal': 0, 'int_conf': 0, 'nat_conf': 0,
        'book': 0, 'book_chapter': 0, 'patent': 0,
    }
    
    flat_text = re.sub(r'\s+', ' ', text)
    
    def get_clean_count(m):
        if not m:
            return 0
        val_str = m.group(1) if m.group(1) else m.group(2)
        if val_str:
            val = int(val_str)
            if not (1900 <= val <= 2100):
                return val
        return 0

    # Match counts safely
    m_int_j = re.search(r'\binternational\s+journal[s]?\b[\s\:\-\–\—\=\(]*(\d+)\b|\b(\d+)\s*international\s+journal[s]?\b', flat_text, re.I)
    m_j = re.search(r'\bjournal[s]?\b[\s\:\-\–\—\=\(]*(\d+)\b|\b(\d+)\s*journal[s]?\b', flat_text, re.I)
    explicit_counts['journal'] = get_clean_count(m_int_j) or get_clean_count(m_j)

    m_int_c = re.search(r'\binternational\s+conference[s]?\b[\s\:\-\–\—\=\(]*(\d+)\b|\b(\d+)\s*international\s+conference[s]?\b', flat_text, re.I)
    explicit_counts['int_conf'] = get_clean_count(m_int_c)

    m_nat_c = re.search(r'\bnational\s+conference[s]?\b[\s\:\-\–\—\=\(]*(\d+)\b|\b(\d+)\s*national\s+conference[s]?\b', flat_text, re.I)
    explicit_counts['nat_conf'] = get_clean_count(m_nat_c)

    m_b = re.search(r'\bbook[s]?\b(?![\s\-\–\—]*chapter)[\s\:\-\–\—\=\(]*(\d+)\b|\b(\d+)\s*book[s]?\b(?![\s\-\–\—]*chapter)', flat_text, re.I)
    explicit_counts['book'] = get_clean_count(m_b)

    m_bc = re.search(r'\bbook\s+chapter[s]?\b[\s\:\-\–\—\=\(]*(\d+)\b|\b(\d+)\s*book\s+chapter[s]?\b', flat_text, re.I)
    explicit_counts['book_chapter'] = get_clean_count(m_bc)

    m_pat = re.search(r'\bpatent[s]?\b[\s\:\-\–\—\=\(]*(\d+)\b|\b(\d+)\s*patent[s]?\b', flat_text, re.I)
    explicit_counts['patent'] = get_clean_count(m_pat)

    # Check for explicit stated patterns using COUNT_PATTERNS
    for key, pat in COUNT_PATTERNS.items():
        m = pat.search(text)
        if m:
            val = int(m.group(1))
            if not (1900 <= val <= 2100):
                explicit_counts[key] = max(explicit_counts[key], val)

    # Split middle-of-line entry numbers to separate lines so they start a new entry correctly
    lines = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        line_split = re.sub(r'\s+(\d+[\.\)\-]\s+)', r'\n\1', line)
        for part in line_split.splitlines():
            if part.strip():
                lines.append(part.strip())

    raw_entries = _group_entries(lines)

    publications = []

    for entry in raw_entries:
        if not _is_valid_publication(entry):
            continue

        pub_type = _classify(entry)

        y = YEAR_RE.search(entry)
        year = y.group(0) if y else ''

        title, _ = _split_title_venue(entry)

        pub = {
            'type': pub_type,
            'title': title,
            'year': year,
            'raw': entry,
        }

        if pub_type == 'Journal':
            pub.update(_extract_journal_details(entry))
            counts['journal'] += 1
        elif pub_type == 'International Conference':
            pub.update(_extract_conference_details(entry))
            pub.update({'impact_factor': 'N/A', 'scopus_indexed': 'Unknown'})
            counts['int_conf'] += 1
        elif pub_type == 'National Conference':
            pub.update(_extract_conference_details(entry))
            pub.update({'impact_factor': 'N/A', 'scopus_indexed': 'Unknown'})
            counts['nat_conf'] += 1
        elif pub_type == 'Book Chapter':
            pub.update({'journal_name': '', 'journal_details': '',
                        'impact_factor': 'N/A', 'scopus_indexed': 'Unknown'})
            counts['book_chapter'] += 1
        elif pub_type == 'Book':
            pub.update({'journal_name': '', 'journal_details': '',
                        'impact_factor': 'N/A', 'scopus_indexed': 'Unknown'})
            counts['book'] += 1
        elif pub_type == 'Patent':
            pub.update({'journal_name': '', 'journal_details': '',
                        'impact_factor': 'N/A', 'scopus_indexed': 'Unknown'})
            counts['patent'] += 1

        publications.append(pub)

    # Use maximum of parsed entries vs explicit counts
    for key in counts.keys():
        counts[key] = max(explicit_counts.get(key, 0), counts[key])

    return {'counts': counts, 'publications': publications}


# ---------------------------------------------------------------------------
# Designation extraction helper
# ---------------------------------------------------------------------------

_DESIGNATION_PREFIX_RE = re.compile(
    r'^[\w\s,.\-–/]+(?:till\s*date|present|current|\d{4})\s*[:\-–]\s*',
    re.IGNORECASE,
)

_WORKING_AS_RE = re.compile(r'^(?:working|serving|appointed|joined|designated)\s+as\s+', re.IGNORECASE)


def extract_designation(raw: str) -> str:
    text = raw.strip()
    text = _DESIGNATION_PREFIX_RE.sub('', text).strip()
    text = _WORKING_AS_RE.sub('', text).strip()
    return text