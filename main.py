import sys
import os
import streamlit as st
from pathlib import Path
from io import BytesIO
import pandas as pd

# Ensure project root is on sys.path so local packages can be imported when
# running via `streamlit run main.py` or other entrypoints.
PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

try:
    from extractor.text_extractor import extract_text_from_file
except Exception as e:
    import traceback
    print('Failed to import extractor.text_extractor:', e)
    traceback.print_exc()
    raise

from section_detector.detector import detect_sections
from parsers.education_parser import parse_education
from parsers.experience_parser import parse_experience
from parsers.publication_parser import parse_publications
from validator.validator import compute_confidence
from excel_generator.generator import generate_excels
from utils.helpers import extract_email, extract_phone, extract_name
from parsers.simple_parsers import parse_awards, parse_memberships, parse_patents
from llm.ollama_client import call_ollama
from llm.schema import validate_and_extract
import tempfile

st.set_page_config(page_title='Faculty Resume Evaluation System', layout='wide')

# Page title and description
st.title('📋 Faculty Resume Evaluation System')
st.markdown('Extract and analyze faculty information from resumes in bulk.')

# Initialize session state
if 'logs' not in st.session_state:
    st.session_state.logs = []
if 'result' not in st.session_state:
    st.session_state.result = None
if 'uploaded_files' not in st.session_state:
    st.session_state.uploaded_files = []

def log(msg):
    st.session_state.logs.append(msg)

# Advanced Settings Sidebar
with st.sidebar:
    st.header('⚙️ Advanced Settings')
    with st.expander('LLM & Extraction', expanded=False):
        enable_llm = st.checkbox('Enable Local LLM Fallback (Ollama)', value=False)
        force_llm = st.checkbox('Force LLM for all resumes', value=False)
        llm_attempts = st.number_input('LLM Attempts', min_value=1, max_value=10, value=3)
        llm_backoff = st.number_input('LLM Backoff Factor (sec)', min_value=0.0, max_value=10.0, value=1.0, step=0.5)
        llm_conf_threshold = st.slider('Confidence Threshold', min_value=0, max_value=100, value=60)
        ollama_host = st.text_input('Ollama Host', value='http://127.0.0.1:11434')
        ollama_model = st.text_input('Ollama Model', value='qwen2.5:7b-instruct')

    st.markdown('---')
    st.markdown('**About**')
    st.caption('Extract and organize faculty profile data from PDF and DOCX resumes.')

# Main Content Layout
col1, col2 = st.columns([2, 1])

with col1:
    st.subheader('📤 Upload Resumes')
    uploaded_files = st.file_uploader(
        'Select one or more resume files (PDF, DOCX, DOC)',
        type=['pdf', 'docx', 'doc'],
        accept_multiple_files=True,
        key='uploader'
    )
    st.session_state.uploaded_files = uploaded_files or []

with col2:
    st.subheader('🚀 Process')
    process_button = st.button('Process Resumes', use_container_width=True, type='primary')


# Main processing pipeline
if process_button:
    if not st.session_state.uploaded_files:
        st.error('Please upload at least one resume file.')
    else:
        st.session_state.logs = []

        entries = [('uploaded', f) for f in st.session_state.uploaded_files]
        total = len(entries)
        success = 0
        failed = 0
        master_rows = []
        pub_rows = []

        # Progress tracking containers
        progress_bar = st.progress(0, text='Initializing...')
        status_text = st.empty()
        current_file_display = st.empty()

        for i, (etype, f) in enumerate(entries, start=1):
            name_display = f.name

            progress_pct = i / total if total > 0 else 1.0
            progress_bar.progress(progress_pct, text=f'Processing {i}/{total}')
            status_text.text(f'📄 {name_display}')

            try:
                # Handle uploaded file
                with tempfile.NamedTemporaryFile(delete=False, suffix=Path(f.name).suffix) as tmp:
                    tmp.write(f.read())
                    tmp_path = tmp.name

                text = extract_text_from_file(str(tmp_path))
                try:
                    os.unlink(tmp_path)
                except Exception:
                    pass

                sections = detect_sections(text)

                extracted_name_val = extract_name(text)
                personal = {
                    'Source File': name_display,
                    'Name': extracted_name_val,
                    'Email': extract_email(text, name=extracted_name_val),
                    'Phone': extract_phone(text),
                }

                edu = parse_education(sections.get('education', ''))
                exp = parse_experience(sections.get('experience', ''), full_text=text)
                pubs = parse_publications(sections.get('publications', ''))

                row = {
                    'Source File': name_display,
                    'Name': personal.get('Name', ''),
                    'Email': personal.get('Email', ''),
                    'Phone': personal.get('Phone', ''),
                    'UG Degree': edu.get('ug_degree', ''),
                    'UG Branch': edu.get('ug_branch', ''),
                    'UG University': edu.get('ug_university', ''),
                    'UG Year': edu.get('ug_year', ''),
                    'PG Degree': edu.get('pg_degree', ''),
                    'PG Branch': edu.get('pg_branch', ''),
                    'PG University': edu.get('pg_university', ''),
                    'PG Year': edu.get('pg_year', ''),
                    'PhD University': edu.get('phd_university', ''),
                    'PhD Year': edu.get('phd_year', ''),
                }

                row.update(exp.get('summary', {}))

                pub_counts = pubs.get('counts', {})
                row['Journal Count'] = pub_counts.get('journal', 0)
                row['International Conference Count'] = pub_counts.get('int_conf', 0)
                row['National Conference Count'] = pub_counts.get('nat_conf', 0)
                row['Book Count'] = pub_counts.get('book', 0)
                row['Book Chapter Count'] = pub_counts.get('book_chapter', 0)

                patent_list = parse_patents(sections.get('patents', ''))
                row['Patent Count'] = max(pub_counts.get('patent', 0), len(patent_list))

                awards_list = parse_awards(sections.get('awards', ''))
                row['Awards Count'] = len(awards_list)

                memberships_list = parse_memberships(sections.get('memberships', ''))
                row['Membership Count'] = len(memberships_list)

                row['Confidence Score'] = compute_confidence(personal, edu, exp, pubs)

                # LLM fallback if enabled
                if enable_llm and (force_llm or row['Confidence Score'] < llm_conf_threshold):
                    try:
                        sec_edu = sections.get('education', '')[:1200]
                        sec_exp = sections.get('experience', '')[:1200]
                        sec_pubs = sections.get('publications', '')[:1200]
                        prompt = (
                            "You are an extraction assistant.\n"
                            "Return ONLY a single valid JSON object and nothing else.\n"
                            "Follow this schema: {name, email, phone, current_designation, current_department, current_organization, "
                            "education:{ug_degree,ug_branch,ug_university,ug_year,pg_degree,pg_branch,pg_university,pg_year,phd_university,phd_year}, "
                            "experience:{total_experience_years}, publications:[{type,title,journal,publisher,year}]}.\n"
                            "If a field is not present, return an empty string or empty array.\n"
                            "Sections:\n---EDUCATION---\n" + sec_edu + "\n---EXPERIENCE---\n" + sec_exp + "\n---PUBLICATIONS---\n" + sec_pubs
                        )
                        out = call_ollama(ollama_model, prompt, host=ollama_host, attempts=int(llm_attempts), backoff_factor=float(llm_backoff))
                        parsed = validate_and_extract(out)

                        if parsed.get('name'):
                            row['Name'] = parsed.get('name')
                        if parsed.get('email'):
                            row['Email'] = parsed.get('email')
                        if parsed.get('phone'):
                            row['Phone'] = parsed.get('phone')
                        ed = parsed.get('education', {})
                        for k in ['ug_degree', 'ug_branch', 'ug_university', 'ug_year', 'pg_degree', 'pg_branch', 'pg_university', 'pg_year', 'phd_university', 'phd_year']:
                            if ed.get(k):
                                row[k] = ed.get(k)
                        exp_parsed = parsed.get('experience', {})
                        if exp_parsed.get('total_experience_years'):
                            row['Total Experience'] = exp_parsed.get('total_experience_years')
                    except Exception as e:
                        log(f'LLM fallback failed for {name_display}: {str(e)[:50]}')

                master_rows.append(row)

                for pub in pubs.get('publications', []):
                    pub_row = {
                        'Faculty Name': row.get('Name', ''),
                        'Designation': exp.get('current_designation', ''),
                        'Department': exp.get('current_department', ''),
                        'Publication Type': pub.get('type', ''),
                        'Title of Paper': pub.get('title', '') if pub.get('title') else pub.get('raw', ''),
                        'Journal Name': pub.get('journal_name') if pub.get('journal_name') else pub.get('conference_name', ''),
                        'Published Under / Publisher': pub.get('journal_details', ''),
                        'Year of Publication': pub.get('year', ''),
                        'Scopus Indexed': pub.get('scopus_indexed', 'Unknown'),
                        'Source Resume': name_display,
                    }
                    pub_rows.append(pub_row)

                success += 1
                log(f'✓ {name_display}')
            except Exception as e:
                failed += 1
                log(f'✗ {name_display}: {str(e)[:50]}')

        # Generate Excel files
        # generate_excels returns (master_df: DataFrame, publication_wb: openpyxl Workbook)
        master_df, publication_wb = generate_excels(master_rows, pub_rows)

        # Build pubs_df from pub_rows for preview and flat download
        pubs_df = pd.DataFrame(pub_rows) if pub_rows else pd.DataFrame()

        # Create combined workbook (master sheet + per-faculty publication sheets)
        combined_buffer = BytesIO()
        with pd.ExcelWriter(combined_buffer, engine="openpyxl") as writer:
            master_df.to_excel(writer, sheet_name="Faculty Data", index=False)

            # Copy all publication sheets from the openpyxl workbook
            for ws in publication_wb.worksheets:
                new_sheet = writer.book.create_sheet(title=ws.title)
                for ws_row in ws.iter_rows(values_only=True):
                    new_sheet.append(ws_row)

        combined_bytes = combined_buffer.getvalue()

        # Master Excel bytes (flat DataFrame)
        master_buffer = BytesIO()
        master_df.to_excel(master_buffer, index=False, engine='openpyxl')
        master_bytes = master_buffer.getvalue()

        # Publications Excel bytes (openpyxl workbook with per-faculty sheets)
        pubs_buffer = BytesIO()
        publication_wb.save(pubs_buffer)
        pubs_bytes = pubs_buffer.getvalue()

        st.session_state.result = {
            'total': total,
            'success': success,
            'failed': failed,
            'master_bytes': master_bytes,
            'pubs_bytes': pubs_bytes,
            'combined_bytes': combined_bytes,
            'master_df': master_df,
            'pubs_df': pubs_df,
        }

        progress_bar.progress(1.0, text='Complete!')
        status_text.empty()

# Display results if processing completed
if st.session_state.result:
    result = st.session_state.result

    st.markdown('---')
    st.subheader('📊 Results Summary')

    # Statistics cards
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric('Total Resumes', result['total'])
    with col2:
        st.metric('Successfully Processed', result['success'], delta=result['total'] - result['success'] if result['failed'] > 0 else 0)
    with col3:
        st.metric('Failed', result['failed'])
    with col4:
        avg_conf = result['master_df']['Confidence Score'].mean() if not result['master_df'].empty else 0
        st.metric('Avg Confidence', f'{round(avg_conf, 1)}%')

    # Data previews
    st.markdown('---')
    st.subheader('📋 Data Preview')

    tab1, tab2 = st.tabs(['Faculty Data', 'Publications'])

    with tab1:
        st.dataframe(result['master_df'], use_container_width=True, height=300)

    with tab2:
        st.dataframe(result['pubs_df'], use_container_width=True, height=300)

    # Download buttons
    st.markdown('---')
    st.subheader('⬇️ Download Results')

    col1, col2, col3 = st.columns(3)
    with col1:
        st.download_button(
            label='📥 Master Excel',
            data=result['master_bytes'],
            file_name='master_faculty_database.xlsx',
            mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            use_container_width=True
        )
    with col2:
        st.download_button(
            label='📥 Publications Excel',
            data=result['pubs_bytes'],
            file_name='publication_details.xlsx',
            mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            use_container_width=True
        )
    with col3:
        st.download_button(
            label='📥 Combined Workbook',
            data=result['combined_bytes'],
            file_name='faculty_evaluation_report.xlsx',
            mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            use_container_width=True
        )

    # Processing logs (collapsible)
    with st.expander('📝 Processing Logs', expanded=False):
        st.code('\n'.join(st.session_state.logs[-100:] or ['No logs available']), language='text')