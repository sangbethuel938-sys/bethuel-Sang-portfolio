
import json
import base64
import html
import mimetypes
import urllib.request
import urllib.error
import re
import os
import shutil
import hashlib
import hmac
import secrets
from pathlib import Path
from datetime import datetime
import streamlit as st
import pandas as pd


from cv_generator import (
    REPORTLAB_AVAILABLE, build_tailored_package, cv_plain_text,
    cv_docx_bytes, cv_pdf_bytes, humanized_cover_letter,
    cover_letter_docx_from_text, cover_letter_pdf_from_text, package_zip
)

from PIL import Image

# Transparent browser-tab favicon.
# This avoids Streamlit's default icon and does not require an icon file in assets.
transparent_icon = Image.new("RGBA", (32, 32), (0, 0, 0, 0))

st.set_page_config(
    page_title="Bethuel Sang | Portfolio",
    page_icon=transparent_icon,
    layout="wide"
)

BASE = Path(__file__).parent

# Local use: files stay beside app.py.
# Cloud/Docker use: set PORTFOLIO_STORAGE to a persistent mounted directory.
STORAGE_ROOT = Path(os.environ.get("PORTFOLIO_STORAGE", str(BASE))).resolve()

DATA = STORAGE_ROOT / "data"
ASSETS = STORAGE_ROOT / "assets"
PROJECT_ASSETS = ASSETS / "projects"
PROFILE_ASSETS = ASSETS / "profile"

for folder in [DATA, ASSETS, PROJECT_ASSETS, PROFILE_ASSETS]:
    folder.mkdir(parents=True, exist_ok=True)

def _seed_persistent_storage():
    """Copy repository starter content into an empty persistent volume once."""
    if STORAGE_ROOT == BASE.resolve():
        return

    seed_data = BASE / "data"
    if seed_data.exists():
        for src_file in seed_data.glob("*.json"):
            # Authentication is created from ADMIN_PASSWORD on first cloud run.
            if src_file.name == "admin_auth.json":
                continue
            dst_file = DATA / src_file.name
            if not dst_file.exists():
                shutil.copy2(src_file, dst_file)

    seed_assets = BASE / "assets"
    if seed_assets.exists():
        for src_file in seed_assets.rglob("*"):
            if not src_file.is_file():
                continue
            rel = src_file.relative_to(seed_assets)
            dst_file = ASSETS / rel
            dst_file.parent.mkdir(parents=True, exist_ok=True)
            if not dst_file.exists():
                shutil.copy2(src_file, dst_file)

_seed_persistent_storage()

PROFILE_FILE = DATA / "profile.json"
PROJECTS_FILE = DATA / "projects.json"
EXPERIENCE_FILE = DATA / "experience.json"
SKILLS_FILE = DATA / "skills.json"
EDUCATION_FILE = DATA / "education.json"
CERTIFICATIONS_FILE = DATA / "certifications.json"
SITE_CONTENT_FILE = DATA / "site_content.json"
ADMIN_AUTH_FILE = DATA / "admin_auth.json"

DEFAULT_SITE_CONTENT = {
    "nav_home": "Home",
    "nav_projects": "Projects",
    "nav_experience": "Experience",
    "nav_skills": "Skills",
    "nav_education": "Education",
    "nav_contact": "Contact",

    "linkedin_button": "LinkedIn",
    "github_button": "GitHub",
    "download_cv_button": "Download CV",

    "snapshot_current_role_label": "Current role",
    "snapshot_current_role_value": "",
    "snapshot_core_tools_label": "Core tools",
    "snapshot_core_tools_value": "Power BI · Python · SQL · Excel",
    "snapshot_portfolio_label": "Portfolio",
    "snapshot_projects_suffix": "Projects",
    "snapshot_development_label": "Professional development",
    "snapshot_certifications_suffix": "Certifications & Training",

    "home_about_eyebrow": "About me",
    "home_about_title": "Where trade insight meets operational clarity.",
    "home_featured_eyebrow": "Featured work",
    "home_featured_title": "Selected Projects",

    "projects_eyebrow": "Portfolio",
    "projects_title": "Projects",
    "projects_description": "Analytics, automation and trade-development work designed for better decisions.",
    "projects_filter_label": "Filter by category",

    "experience_eyebrow": "Career",
    "experience_title": "Experience",

    "skills_eyebrow": "Capabilities",
    "skills_title": "A practical toolkit for analytical, commercial and operational work.",
    "certifications_eyebrow": "Professional Development",
    "certifications_title": "Selected Certifications & Training",
    "additional_certifications_label": "Additional certifications",

    "education_eyebrow": "Education",
    "education_title": "Building analytical depth with business perspective.",

    "contact_eyebrow": "Contact",
    "contact_title": "Let’s turn insight into action.",
    "contact_email_label": "Email",
    "contact_phone_label": "Phone",
    "contact_location_label": "Location",

    "project_view_button": "View Project",
    "project_github_button": "GitHub",
    "project_case_study_label": "Case study",
    "project_challenge_label": "Challenge",
    "project_solution_label": "Solution",
    "project_impact_label": "Impact",
    "project_screenshots_label": "Screenshots",
    "project_empty_image_text": "Add a project screenshot from Admin - Edit Project"
}

def _supabase_credentials():
    try:
        url = str(st.secrets.get("SUPABASE_URL", "")).strip().rstrip("/")
        key = str(
            st.secrets.get("SUPABASE_SECRET_KEY", "")
            or st.secrets.get("SUPABASE_SERVICE_KEY", "")
        ).strip()
        return url, key
    except Exception:
        return "", ""

def _supabase_headers(extra=None):
    _, key = _supabase_credentials()
    headers = {
        "apikey": key,
        "Accept": "application/json",
        "User-Agent": "BethuelPortfolio/1.0",
    }
    if extra:
        headers.update(extra)
    return headers

def _safe_http_error(exc):
    status = getattr(exc, "code", "")
    reason = getattr(exc, "reason", "")
    body = ""
    try:
        body = exc.read().decode("utf-8", errors="replace")
    except Exception:
        pass
    body = body[:600]
    parts = [p for p in [f"HTTP {status}" if status else "", str(reason), body] if p]
    return " | ".join(parts)

def _supabase_request(method, path, payload=None, headers=None, timeout=15):
    url, key = _supabase_credentials()
    if not url:
        raise RuntimeError("SUPABASE_URL is missing from Streamlit Secrets.")
    if not key:
        raise RuntimeError("SUPABASE_SECRET_KEY is missing from Streamlit Secrets.")

    target = url + path
    data = None
    request_headers = _supabase_headers(headers)

    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request_headers.setdefault("Content-Type", "application/json")

    req = urllib.request.Request(
        target,
        data=data,
        headers=request_headers,
        method=method,
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            raw = response.read()
            if not raw:
                return None
            text = raw.decode("utf-8", errors="replace")
            try:
                return json.loads(text)
            except Exception:
                return text
    except urllib.error.HTTPError as exc:
        raise RuntimeError(_safe_http_error(exc)) from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Network error: {exc.reason}") from exc

def supabase_health():
    url, key = _supabase_credentials()

    if not url:
        return False, "SUPABASE_URL is missing from Streamlit Secrets."
    if not url.startswith("https://") or ".supabase.co" not in url:
        return False, "SUPABASE_URL does not look like a valid Supabase project URL."
    if not key:
        return False, "SUPABASE_SECRET_KEY is missing from Streamlit Secrets."
    if key.startswith("sb_publishable_"):
        return False, "A publishable key is configured. Use the private sb_secret_ key."
    if not (key.startswith("sb_secret_") or key.startswith("eyJ")):
        return False, "The configured key does not look like a Supabase secret/service-role key."

    try:
        _supabase_request("GET", "/rest/v1/portfolio_store?select=key&limit=1")
        return True, "Direct REST connection to portfolio_store succeeded."
    except Exception as exc:
        return False, f"Direct Supabase REST test failed: {exc}"

def supabase_enabled():
    ok, _ = supabase_health()
    return ok

def _store_key(path):
    return Path(path).stem

def _local_read_json(path, fallback):
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        pass
    return fallback

def _local_write_json(path, data):
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass

def read_json(path, fallback):
    key = _store_key(path)
    ok, _ = supabase_health()

    if ok:
        try:
            encoded_key = urllib.parse.quote(key, safe="")
            rows = _supabase_request(
                "GET",
                f"/rest/v1/portfolio_store?select=value&key=eq.{encoded_key}&limit=1",
            ) or []

            if isinstance(rows, list) and rows:
                value = rows[0].get("value")
                if value is not None:
                    return value

            seed = _local_read_json(path, fallback)
            _supabase_request(
                "POST",
                "/rest/v1/portfolio_store?on_conflict=key",
                {"key": key, "value": seed},
                headers={"Prefer": "resolution=merge-duplicates,return=representation"},
            )
            return seed

        except Exception as exc:
            st.session_state["_supabase_read_error"] = str(exc)

    return _local_read_json(path, fallback)

def write_json(path, data):
    _local_write_json(path, data)

    url, secret = _supabase_credentials()
    if not url and not secret:
        return

    ok, message = supabase_health()
    if not ok:
        raise RuntimeError("Permanent save failed. " + message)

    key = _store_key(path)

    try:
        result = _supabase_request(
            "POST",
            "/rest/v1/portfolio_store?on_conflict=key",
            {"key": key, "value": data},
            headers={"Prefer": "resolution=merge-duplicates,return=representation"},
        )

        if not isinstance(result, list) or not result:
            raise RuntimeError("Supabase did not return the saved row.")

        encoded_key = urllib.parse.quote(key, safe="")
        verify = _supabase_request(
            "GET",
            f"/rest/v1/portfolio_store?select=key&key=eq.{encoded_key}&limit=1",
        ) or []

        if not isinstance(verify, list) or not verify:
            raise RuntimeError("Saved row could not be read back.")

        st.session_state["_last_supabase_save"] = key
        st.session_state.pop("_supabase_write_error", None)

    except Exception as exc:
        st.session_state["_supabase_write_error"] = str(exc)
        raise RuntimeError(
            f"Supabase did not save '{key}'. Details: {exc}"
        ) from exc

def _supabase_bucket():
    try:
        return str(
            st.secrets.get("SUPABASE_BUCKET", "portfolio-assets")
        ).strip() or "portfolio-assets"
    except Exception:
        return "portfolio-assets"

def _storage_public_url(rel_path):
    if not rel_path:
        return ""
    url, _ = _supabase_credentials()
    if not url:
        return ""
    bucket = urllib.parse.quote(_supabase_bucket(), safe="")
    encoded_path = "/".join(
        urllib.parse.quote(part, safe="")
        for part in str(rel_path).replace("\\", "/").split("/")
    )
    return f"{url}/storage/v1/object/public/{bucket}/{encoded_path}"

def _storage_download(rel_path):
    if not rel_path:
        return None
    url, _ = _supabase_credentials()
    if not url:
        return None

    bucket = urllib.parse.quote(_supabase_bucket(), safe="")
    encoded_path = "/".join(
        urllib.parse.quote(part, safe="")
        for part in str(rel_path).replace("\\", "/").split("/")
    )
    target = f"{url}/storage/v1/object/{bucket}/{encoded_path}"

    try:
        req = urllib.request.Request(
            target,
            headers=_supabase_headers(),
            method="GET"
        )
        with urllib.request.urlopen(req, timeout=20) as response:
            return response.read()
    except Exception:
        return None

def _storage_upload(rel_path, payload, content_type):
    url, _ = _supabase_credentials()
    if not url:
        raise RuntimeError("Supabase URL is not configured.")

    bucket = urllib.parse.quote(_supabase_bucket(), safe="")
    encoded_path = "/".join(
        urllib.parse.quote(part, safe="")
        for part in str(rel_path).replace("\\", "/").split("/")
    )
    target = f"{url}/storage/v1/object/{bucket}/{encoded_path}"

    headers = _supabase_headers({
        "Content-Type": content_type or "application/octet-stream",
        "x-upsert": "true",
    })

    req = urllib.request.Request(
        target,
        data=payload,
        headers=headers,
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            return response.read()
    except urllib.error.HTTPError as exc:
        raise RuntimeError(_safe_http_error(exc)) from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Storage network error: {exc.reason}") from exc

def asset_bytes(rel_path):
    if not rel_path:
        return None
    rel_path = str(rel_path).strip()
    if rel_path.startswith("http://") or rel_path.startswith("https://"):
        return None

    local_path = STORAGE_ROOT / rel_path
    if local_path.exists():
        try:
            return local_path.read_bytes()
        except Exception:
            pass

    return _storage_download(rel_path)

def asset_source(rel_path):
    if not rel_path:
        return ""
    rel_path = str(rel_path).strip()

    if rel_path.startswith("http://") or rel_path.startswith("https://"):
        return rel_path

    local_path = STORAGE_ROOT / rel_path
    if local_path.exists():
        return str(local_path)

    return _storage_public_url(rel_path)

def set_admin_notice(message, kind="success"):
    """Store a one-time Admin message so it survives st.rerun()."""
    st.session_state["admin_notice"] = {
        "message": message,
        "kind": kind,
        "time": datetime.now().strftime("%H:%M:%S"),
    }

def show_admin_notice():
    """Display and clear the latest Admin action response."""
    notice = st.session_state.pop("admin_notice", None)
    if not notice:
        return

    message = notice.get("message", "Saved.")
    kind = notice.get("kind", "success")
    saved_time = notice.get("time", "")

    # Toast gives immediate visual feedback without decorative icons.
    try:
        st.toast(f"{message}  {saved_time}")
    except Exception:
        pass

    # The full-width message remains clearly visible on the Admin page.
    if kind == "error":
        st.error(message)
    elif kind == "warning":
        st.warning(message)
    elif kind == "info":
        st.info(message)
    else:
        st.success(message)


# ---------- Local Admin Authentication ----------
# The password is stored as a PBKDF2 hash, not as readable text.
def _password_hash(password, salt_hex, iterations=260000):
    return hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        bytes.fromhex(salt_hex),
        iterations
    ).hex()

def _create_auth_record(password):
    salt = secrets.token_hex(16)
    iterations = 260000
    return {
        "salt": salt,
        "iterations": iterations,
        "password_hash": _password_hash(password, salt, iterations)
    }

def _initial_admin_password():
    env_password = os.environ.get("ADMIN_PASSWORD", "").strip()
    if env_password:
        return env_password

    try:
        secret_password = st.secrets.get("ADMIN_PASSWORD", "")
        if secret_password:
            return secret_password
    except Exception:
        pass

    # Local fallback only. For internet deployment, always set ADMIN_PASSWORD.
    return "ChangeMe123!"

def _ensure_admin_auth():
    if not ADMIN_AUTH_FILE.exists():
        write_json(ADMIN_AUTH_FILE, _create_auth_record(_initial_admin_password()))

def verify_admin_password(password):
    _ensure_admin_auth()
    record = read_json(ADMIN_AUTH_FILE, {})
    if not record:
        return False
    expected = record.get("password_hash", "")
    actual = _password_hash(
        password,
        record.get("salt", ""),
        int(record.get("iterations", 260000))
    )
    return hmac.compare_digest(actual, expected)

def reset_admin_password(new_password):
    write_json(ADMIN_AUTH_FILE, _create_auth_record(new_password))

_ensure_admin_auth()

def slugify(text):
    text = re.sub(r"[^a-zA-Z0-9]+", "-", text.strip().lower())
    return text.strip("-") or f"project-{int(datetime.now().timestamp())}"

def save_uploaded_file(uploaded_file, folder, stem=None):
    if not uploaded_file:
        return ""

    ext = uploaded_file.name.split(".")[-1].lower()
    if stem:
        filename = f"{slugify(stem)}.{ext}"
    else:
        filename = f"{int(datetime.now().timestamp()*1000)}-{slugify(uploaded_file.name.rsplit('.',1)[0])}.{ext}"

    try:
        relative_folder = folder.relative_to(STORAGE_ROOT)
    except Exception:
        relative_folder = Path("assets")

    rel_path = str((relative_folder / filename)).replace("\\", "/")
    payload = bytes(uploaded_file.getbuffer())

    local_path = STORAGE_ROOT / rel_path
    local_path.parent.mkdir(parents=True, exist_ok=True)
    local_path.write_bytes(payload)

    url, secret = _supabase_credentials()
    if url and secret:
        try:
            _storage_upload(
                rel_path,
                payload,
                getattr(uploaded_file, "type", None) or "application/octet-stream",
            )
        except Exception as exc:
            st.warning(
                "The file was saved for this session, but permanent Supabase "
                f"Storage upload failed: {exc}"
            )

    return rel_path

def asset_exists(rel_path):
    if not rel_path:
        return False
    rel_path = str(rel_path).strip()
    if rel_path.startswith("http://") or rel_path.startswith("https://"):
        return True
    if (STORAGE_ROOT / rel_path).exists():
        return True
    return bool(_storage_public_url(rel_path))

def asset_data_uri(rel_path):
    if not rel_path:
        return ""
    rel_path = str(rel_path).strip()
    if rel_path.startswith("http://") or rel_path.startswith("https://"):
        return rel_path
    local_path = STORAGE_ROOT / rel_path
    if local_path.exists():
        try:
            mime, _ = mimetypes.guess_type(local_path.name)
            if not mime or not mime.startswith("image/"):
                mime = "image/png"
            encoded = base64.b64encode(local_path.read_bytes()).decode("ascii")
            return f"data:{mime};base64,{encoded}"
        except Exception:
            pass
    return _storage_public_url(rel_path)


# ---------- Built-in portfolio fallbacks ----------
# These keep the public portfolio populated even if Streamlit Cloud restores
# an empty/missing JSON file. Admin edits can still override these values.
DEFAULT_PROFILE = {'name': 'Bethuel Sang', 'headline': 'Business & Data Analyst · Trade Development & Market Intelligence', 'hero_title': 'Turning data, trade intelligence and business processes into better decisions.', 'summary': 'Business and data analytics professional with experience in trade development, market intelligence, stakeholder engagement, business reporting and operational analysis. In my current role as Trade Development Assistant at the East African Tea Trade Association (EATTA), I analyse tea auction and market data, identify pricing and market trends, prepare management reports and dashboards, and support trade development initiatives across the East African tea industry.', 'about': 'My work involves collaborating with producers, buyers, brokers, warehouses, packers, regulators and other industry stakeholders. I also support risk management, operational improvement and strategic projects within the organisation. I use Power BI, Excel, Python, SQL, PostgreSQL, Power Query and Streamlit to improve reporting, data management and business processes. Before EATTA, I gained experience in demand planning, material forecasting, inventory management, sales operations, customer acquisition and business relationship management. I have a background in Statistics and I am currently pursuing an MBA in Strategic Management. My career interests include Business Analytics, Data Analytics, Business Intelligence, Market Intelligence, Trade Development, Commercial Analytics and Strategy.', 'location': 'Mombasa County, Kenya', 'email': 'sangbethuel938@gmail.com', 'phone': '0702733260', 'linkedin': 'https://www.linkedin.com/in/bethuel-sang', 'github': '', 'availability': 'Career interests include Business Analytics, Data Analytics, Business Intelligence, Market Intelligence, Trade Development, Commercial Analytics and Strategy.', 'profile_image': 'https://qmqhtpjdhaidjeqkehqq.supabase.co/storage/v1/object/public/portfolio-assets/Profiel.jpg', 'cv_file': 'assets/Bethuel_Sang_Full_Professional_CV.pdf', 'cv_docx_file': 'assets/Bethuel_Sang_Full_Professional_CV.docx', 'facebook': '', 'youtube': ''}
DEFAULT_EXPERIENCE = [{'role': 'Trade Development Assistant', 'company': 'East African Tea Trade Association (EATTA)', 'period': 'June 2023 – Present', 'details': 'Analyse tea auction, pricing and market data to identify trends, performance gaps and commercial insights for management decision-making; Develop Power BI and Excel reports and dashboards covering auction performance, buyer activity, market trends and other key trade indicators; Conduct market intelligence analysis by monitoring regional and international tea markets, competitor activity and emerging industry developments; Coordinate with producers, buyers, brokers, warehouses, packers, regulators and other stakeholders to support efficient trade and auction operations; Support trade development initiatives aimed at improving market access, stakeholder engagement and industry competitiveness; Prepare management reports, market intelligence briefs, presentations and analytical summaries for senior management and industry stakeholders; Support departmental risk identification, assessment, mitigation and compliance activities as Risk Champion; Use Python, Power Query, SQL and automation tools to improve data processing, reporting and operational efficiency; Support strategic and cross-functional projects, including digital registration, QR-based verification, event-management systems and data-quality initiatives; Perform data validation, reconciliation, duplicate analysis and reporting to improve the accuracy and integrity of operational information'}, {'role': 'Trade Development Representative', 'company': 'Twiga Foods', 'period': 'January 2020 – May 2023', 'details': 'Supported vendor acquisition and contracting; Maintained accurate vendor and route information in the Data Management System; Supported adoption of the Twiga m-commerce platform and monitored order accuracy and timeliness; Supported customer retention and route growth; Managed vendor relationships and communicated pricing, promotions and product updates; Ensured efficient use of company resources'}, {'role': 'Demand Planner', 'company': 'China Construction Third Engineering Bureau Co., Ltd.', 'period': 'January 2017 – September 2019', 'details': 'Forecasted material requirements from project schedules and consumption trends; Developed material plans aligned with project timelines, contributing to a 15% reduction in delays on the Naiberi–Dry’s Girls Road Upgrade Project; Monitored inventory and stock availability; Analysed material-consumption trends; Supported procurement planning; Collaborated with procurement, engineering and site teams; Improved demand-planning and inventory-management processes'}, {'role': 'Finance Attaché', 'company': 'National Cereals & Produce Board', 'period': 'May 2014 – August 2014', 'details': 'Supported financial reporting and record maintenance; Verified invoices and supporting documents; Assisted with accounts payable and receivable reconciliation; Maintained audit-ready financial documentation; Supported data entry and record management; Worked with finance and administrative teams on daily operations'}]
DEFAULT_EDUCATION = [{'qualification': 'Master of Business Administration – Strategic Management', 'detail': 'The Open University of Kenya · January 2026 – December 2027 · In Progress'}, {'qualification': 'Bachelor of Applied Statistics with Computing', 'detail': 'University of Eldoret · Mathematics and Computer Science · August 2011 – November 2015'}]
DEFAULT_SKILLS = {'Data & Business Intelligence': ['Power BI', 'Microsoft Excel', 'Power Query', 'Dashboard Development', 'Data Analysis', 'Business Intelligence', 'Data Visualization', 'Business Reporting'], 'Programming & Data': ['Python', 'SQL', 'PostgreSQL', 'Pandas', 'NumPy', 'Data Cleaning', 'Data Validation', 'Data Reconciliation', 'Statistical Analysis'], 'Trade & Commercial': ['Market Intelligence', 'Trade Development', 'Commercial Analysis', 'Business Analysis', 'Stakeholder Management', 'Customer Relationship Management'], 'Planning & Operations': ['Demand Forecasting', 'Material Planning', 'Inventory Management', 'Procurement Planning', 'Process Improvement', 'Operational Analysis'], 'Automation & Digital Tools': ['Streamlit', 'Python Automation', 'QR Systems', 'Digital Registration', 'Workflow Automation', 'OCR', 'Whisper Transcription'], 'Management': ['Strategic Analysis', 'Risk Management', 'Compliance', 'Project Coordination', 'Cross-Functional Collaboration', 'Reporting'], 'Languages': ['Swahili — Full Professional', 'English — Professional Working']}
DEFAULT_CERTIFICATIONS = [{'id': 'introduction-to-cybersecurity', 'title': 'Introduction to Cybersecurity', 'issuer': 'Cisco', 'issued': 'August 2026', 'credential_id': '', 'credential_url': 'https://www.credly.com/badges/80c9ab53-1cf8-4e9a-9a38-c3cfad61f4f8/linked_in_profile', 'skills': [], 'featured': True}, {'id': 'data-analytics-training', 'title': 'Data Analytics Training', 'issuer': 'ICT Authority', 'issued': 'July 2026', 'credential_id': 'ICTA-1784318933-7855-45397', 'credential_url': 'https://training.smartacademy.go.ke/certificate-verification/?certificate_id=ICTA-1784318933-7855-45397', 'skills': [], 'featured': True}, {'id': 'introduction-to-data-science', 'title': 'Introduction to Data Science', 'issuer': 'Moringa School', 'issued': 'July–September 2026', 'credential_id': '', 'credential_url': '', 'skills': [], 'featured': True}, {'id': 'strategic-pause-for-leaders', 'title': 'Strategic Pause for Leaders', 'issuer': 'Open University of Kenya', 'issued': 'May 2026', 'credential_id': '', 'credential_url': 'https://www.linkedin.com/in/bethuel-sang/overlay/Certifications/1334580857/treasury/?profileId=ACoAADtaRHcBAI7CnG3nKfpwYNDt8BdcU1cSDnY', 'skills': [], 'featured': False}, {'id': 'business-modeling-for-entrepreneurs', 'title': 'Business Modeling for Entrepreneurs', 'issuer': 'Open University of Kenya', 'issued': 'May 2026', 'credential_id': '', 'credential_url': 'https://www.linkedin.com/in/bethuel-sang/overlay/Certifications/1235652180/treasury/?profileId=ACoAADtaRHcBAI7CnG3nKfpwYNDt8BdcU1cSDnY', 'skills': [], 'featured': False}, {'id': 'mental-health-awareness', 'title': 'Mental Health Awareness', 'issuer': 'Open University of Kenya', 'issued': 'May 2026', 'credential_id': '', 'credential_url': 'https://www.linkedin.com/in/bethuel-sang/overlay/Certifications/1152873046/treasury/?profileId=ACoAADtaRHcBAI7CnG3nKfpwYNDt8BdcU1cSDnY', 'skills': [], 'featured': False}, {'id': 'quality-management-systems-internal-auditor-training-course', 'title': 'Quality Management Systems Internal Auditor Training Course', 'issuer': 'SGS', 'issued': 'April 2026', 'credential_id': '', 'credential_url': 'https://learning.sgs.com/lmt/!clmscertificate.prVerify?site=sgsssc&in_region=ke&in_token=ODRBQkQxODQ5MzI4NzJGNURGNTI2QjkzRDA5MkNDOEUwMkRENjk2QTdBNUNEMjM3MjdDMzcwMDNGNTJENUFEMA==', 'skills': [], 'featured': True}, {'id': 'data-protection-workshop', 'title': 'Data Protection Workshop', 'issuer': 'Office of Data Protection Commissioner', 'issued': 'August 2025', 'credential_id': 'DP/0825-287/004', 'credential_url': 'https://www.odpc.go.ke/wp-content/uploads/2025/10/ODPC-DP-WORKSHOP-287-EATTA.pdf', 'skills': [], 'featured': True}, {'id': 'microsoft-office-specialist-excel-certification', 'title': 'Microsoft Office Specialist: Excel Certification', 'issuer': 'Coursera', 'issued': 'September 2025', 'credential_id': '', 'credential_url': 'https://coursera.org/share/a1bbc83ea9367381a3fe092997b32d91', 'skills': [], 'featured': True}, {'id': 'marketing-channel-benefits', 'title': 'Marketing Channel Benefits', 'issuer': 'Coursera', 'issued': 'September 2025', 'credential_id': '', 'credential_url': 'https://coursera.org/share/c9f3b3bc40d9ef16e18e2dc2d0f74cc5', 'skills': [], 'featured': False}, {'id': 'automation-for-everyone-tech-benefits-unleashed', 'title': 'Automation for Everyone: Tech Benefits Unleashed', 'issuer': 'Coursera', 'issued': 'September 2025', 'credential_id': '', 'credential_url': 'https://coursera.org/share/2d842119b0ad20953f04adb2fe3cc6de', 'skills': [], 'featured': False}, {'id': 'career-essentials-in-generative-ai-by-microsoft-and-linkedin', 'title': 'Career Essentials in Generative AI by Microsoft and LinkedIn', 'issuer': 'LinkedIn', 'issued': 'September 2025', 'credential_id': '', 'credential_url': 'https://www.linkedin.com/learning/certificates/c85b8aaf5852406769adb04f2463da0cb09a656e093a5719fae3271d60ee80f6/?trk=share_certificate', 'skills': [], 'featured': True}, {'id': 'conflict-resolution-foundations', 'title': 'Conflict Resolution Foundations', 'issuer': 'LinkedIn', 'issued': 'September 2025', 'credential_id': '', 'credential_url': 'https://www.linkedin.com/learning/certificates/98f4497630fb32422bb1f4432e0197cbb62ed843a0e02ba2af6a45190ec4103c/?trk=share_certificate', 'skills': [], 'featured': False}, {'id': 'client-management-and-relationships', 'title': 'Client Management and Relationships', 'issuer': 'LinkedIn', 'issued': 'September 2025', 'credential_id': '', 'credential_url': 'https://www.linkedin.com/learning/certificates/d3795c4c8c3ba987fc18e34ad7ba3dd7c9808538eea3268b02fd2801d677c42e/?trk=share_certificate', 'skills': [], 'featured': False}, {'id': 'key-account-management', 'title': 'Key Account Management', 'issuer': 'LinkedIn', 'issued': 'September 2025', 'credential_id': '', 'credential_url': 'https://www.linkedin.com/learning/certificates/05b6e4a5bc89e8f8d45702dfafd546cf8c926993ec5dc30a2e0c77684cb83e79/?trk=share_certificate', 'skills': [], 'featured': False}, {'id': 'building-rapport-with-customers', 'title': 'Building Rapport with Customers', 'issuer': 'LinkedIn', 'issued': 'September 2025', 'credential_id': '', 'credential_url': 'https://www.linkedin.com/learning/certificates/a914e9ede6a5c741f86f4b25232376bcef86cca60f1db3811ae3f387bd4d9764/?trk=share_certificate', 'skills': [], 'featured': False}, {'id': 'account-management-maintaining-relationships', 'title': 'Account Management: Maintaining Relationships', 'issuer': 'LinkedIn', 'issued': 'September 2025', 'credential_id': '', 'credential_url': 'https://www.linkedin.com/learning/certificates/6b3bc28f6121e842f81a3d3fb468f26f16028013c6b9bd00ea01d173bc71daf9/?trk=share_certificate', 'skills': [], 'featured': False}, {'id': 'using-customer-surveys-to-improve-service', 'title': 'Using Customer Surveys to Improve Service', 'issuer': 'LinkedIn', 'issued': 'September 2025', 'credential_id': '', 'credential_url': 'https://www.linkedin.com/learning/certificates/244b8022d747c6c368ab82f7790e3b4ebf9a9a36b9caa5712b1bb6a10e8e1e5f/?trk=share_certificate', 'skills': [], 'featured': False}, {'id': 'creating-positive-conversations-with-challenging-customers', 'title': 'Creating Positive Conversations with Challenging Customers', 'issuer': 'LinkedIn', 'issued': 'September 2025', 'credential_id': '', 'credential_url': 'https://www.linkedin.com/learning/certificates/fec4d27ec53cce46d3246443bb3531a7c3af87a7deaf809cdcfb8d49d9876bfb?trk=share_certificate', 'skills': [], 'featured': False}, {'id': 'developing-a-service-mindset', 'title': 'Developing a Service Mindset', 'issuer': 'LinkedIn', 'issued': 'September 2025', 'credential_id': '', 'credential_url': 'https://www.linkedin.com/learning/certificates/57cc7a814d4fc0d440216b9068fb40fcc818157499ccaa3c06bbeb76be872b55?trk=share_certificate', 'skills': [], 'featured': False}, {'id': 'problem-solving-and-troubleshooting', 'title': 'Problem-Solving and Troubleshooting', 'issuer': 'LinkedIn', 'issued': 'September 2025', 'credential_id': '', 'credential_url': 'https://www.linkedin.com/learning/certificates/885b8f45647bd2d339acc9e24c66e439c272ccd98be7aa3ccf1049071537d377/?trk=share_certificate', 'skills': [], 'featured': False}, {'id': 'zendesk-customer-service-professional', 'title': 'Zendesk Customer Service Professional', 'issuer': 'LinkedIn', 'issued': 'September 2025', 'credential_id': '', 'credential_url': 'https://www.linkedin.com/learning/certificates/37ac195f4375a17e08f7a9f66c98c5f60f797d68d2ca82eb90b4bb4a0c4ca155/?trk=share_certificate', 'skills': [], 'featured': False}, {'id': 'social-media-marketing-strategy-tiktok-and-instagram-reels', 'title': 'Social Media Marketing Strategy: TikTok and Instagram Reels', 'issuer': 'LinkedIn', 'issued': 'September 2025', 'credential_id': '', 'credential_url': 'https://www.linkedin.com/learning/certificates/1abdc92e3e01f7bfa1b8be90067c9d2ce01d60e49219a12690194ac5ad703339/?trk=share_certificate', 'skills': [], 'featured': False}, {'id': 'managing-teams', 'title': 'Managing Teams', 'issuer': 'LinkedIn', 'issued': 'August 2025', 'credential_id': '', 'credential_url': 'https://www.linkedin.com/learning/certificates/d8c05f1d5d047a4b62379a9992cab8de73d99e461055fddcabad7922b5436860/', 'skills': [], 'featured': False}, {'id': 'developing-your-emotional-intelligence', 'title': 'Developing Your Emotional Intelligence', 'issuer': 'LinkedIn', 'issued': 'August 2025', 'credential_id': '', 'credential_url': 'https://www.linkedin.com/learning/certificates/5356e9908c1344fa9b28f1cbff904f1e79f856200756cb7e13927129b8715631/', 'skills': [], 'featured': False}, {'id': 'ai-in-project-management', 'title': 'AI in Project Management', 'issuer': 'LinkedIn', 'issued': 'August 2025', 'credential_id': '', 'credential_url': 'https://www.linkedin.com/in/bethuel-sang/overlay/Certifications/1708266319/treasury/?profileId=ACoAADtaRHcBAI7CnG3nKfpwYNDt8BdcU1cSDnY', 'skills': [], 'featured': False}, {'id': 'project-management-professional-pmp', 'title': 'Project Management Professional (PMP)', 'issuer': 'Computer Pride', 'issued': 'August 2025', 'credential_id': '', 'credential_url': 'https://www.linkedin.com/in/bethuel-sang/overlay/Certifications/1181202977/treasury/?profileId=ACoAADtaRHcBAI7CnG3nKfpwYNDt8BdcU1cSDnY', 'skills': [], 'featured': False}, {'id': 'integrated-customs-management-system', 'title': 'Integrated Customs Management System', 'issuer': 'KESRA', 'issued': 'April 2024', 'credential_id': 'KESRA/040487', 'credential_url': 'https://www.linkedin.com/in/bethuel-sang/overlay/Certifications/1897472047/treasury/?profileId=ACoAADtaRHcBAI7CnG3nKfpwYNDt8BdcU1cSDnY', 'skills': [], 'featured': True}, {'id': 'microsoft-power-bi-desktop-for-business-intelligence', 'title': 'Microsoft Power BI Desktop for Business Intelligence', 'issuer': 'Udemy', 'issued': 'September 2024', 'credential_id': 'UC-6c61eb4c-eaec-4e4c-86f5-06a82914339c', 'credential_url': 'https://www.udemy.com/certificate/UC-6c61eb4c-eaec-4e4c-86f5-06a82914339c/', 'skills': [], 'featured': True}, {'id': 'supply-chain-management-analytics', 'title': 'Supply Chain Management Analytics', 'issuer': 'Unilever', 'issued': '', 'credential_id': '', 'credential_url': 'https://coursera.org/share/588d21d964e1a3d77bf63f020ee34de1', 'skills': [], 'featured': False}]
DEFAULT_PROJECTS = [{'id': 'tea-auction-power-bi-dashboard', 'title': 'Tea Auction Power BI Dashboard', 'category': 'Business Intelligence', 'status': 'Published', 'featured': True, 'description': 'Interactive dashboard for analysing tea auction performance, pricing trends, volumes, buyer activity and key market indicators.', 'tools': ['Power BI', 'Power Query', 'Excel', 'Data Analysis'], 'challenge': 'Auction and market data needed to be consolidated and presented in a form that management could use quickly.', 'solution': 'Developed a repeatable Power BI reporting workflow with cleaned and transformed auction data.', 'impact': 'Improved visibility of auction performance and supported faster interpretation of pricing and market trends.', 'project_link': 'https://app.powerbi.com/groups/me/reports/fb294c02-d7da-4a86-8c39-00805b5a7adf/aa1b40e6591389ee7c67?experience=power-bi', 'github_link': '', 'cover_image': '', 'gallery': []}, {'id': 'weekly-tea-auction-sale-analysis', 'title': 'Weekly Tea Auction & Sale Analysis', 'category': 'Data Analytics', 'status': 'Published', 'featured': True, 'description': 'Weekly analysis workflow that incorporates auction results and later-week outlot/private-sale activity for a more complete market view.', 'tools': ['Excel', 'Power Query', 'Power BI'], 'challenge': 'Initial auction-close figures did not always represent the complete weekly value because later sales continued during the week.', 'solution': 'Re-analysed the weekly data after the later-week sales period and reconciled the results.', 'impact': 'Produced a more complete weekly reporting view for market and management analysis.', 'project_link': '', 'github_link': '', 'cover_image': '', 'gallery': []}, {'id': 'eatta-sports-day-qr-registration-system', 'title': 'EATTA Sports Day QR Registration System', 'category': 'Automation', 'status': 'Published', 'featured': True, 'description': 'QR-enabled registration and verification workflow for participant tracking, attendance, team registration and item distribution.', 'tools': ['QR Codes', 'Excel', 'Digital Forms', 'Data Validation'], 'challenge': 'Manual registration and verification were slow and prone to duplication.', 'solution': 'Designed a QR-based workflow linked to structured participant records.', 'impact': 'Improved participant verification, tracking and event administration.', 'project_link': '', 'github_link': '', 'cover_image': '', 'gallery': []}, {'id': 'qr-asset-check-in-check-out-system', 'title': 'QR Asset Check-In / Check-Out System', 'category': 'Automation', 'status': 'Published', 'featured': False, 'description': 'Mobile QR workflow for recording asset check-in and check-out transactions.', 'tools': ['Power Apps', 'QR Codes', 'Excel', 'Workflow Design'], 'challenge': 'Asset movements needed a simple mobile tracking process.', 'solution': 'Designed a Power Apps-based QR scanning workflow linked to structured records.', 'impact': 'Created a more traceable and practical asset movement process.', 'project_link': '', 'github_link': '', 'cover_image': '', 'gallery': []}, {'id': 'automated-email-complaint-register', 'title': 'Automated Email Complaint Register', 'category': 'Automation', 'status': 'Published', 'featured': False, 'description': 'Automation for collecting forwarded complaints and structuring them into an ISO-aligned Excel complaint register.', 'tools': ['Python', 'Gmail/IMAP', 'Excel', 'Automation'], 'challenge': 'Complaint emails required manual consolidation and tracking.', 'solution': 'Built a Python workflow to retrieve and structure complaint information in a central register.', 'impact': 'Reduced repetitive manual entry and improved complaint traceability.', 'project_link': '', 'github_link': '', 'cover_image': '', 'gallery': []}, {'id': 'meeting-transcription-automation', 'title': 'Meeting Transcription Automation', 'category': 'Automation', 'status': 'Published', 'featured': False, 'description': 'Automated workflow for turning recorded meetings into text transcripts and organizing completed files.', 'tools': ['Python', 'Whisper', 'File Automation'], 'challenge': 'Recorded meetings required manual transcription and file handling.', 'solution': 'Created a watched-folder workflow using Whisper transcription.', 'impact': 'Reduced manual transcription effort and standardized file handling.', 'project_link': '', 'github_link': '', 'cover_image': '', 'gallery': []}, {'id': 'auction-data-quality-audit', 'title': 'Auction Data Quality Audit', 'category': 'Data Analytics', 'status': 'Published', 'featured': False, 'description': 'Data-quality workflow for identifying duplicates, inconsistencies, reconciliation issues and reporting errors in auction-related data.', 'tools': ['Excel', 'Power Query', 'Python', 'Data Cleaning'], 'challenge': 'Operational datasets contained duplicate and inconsistent records.', 'solution': 'Applied structured validation, reconciliation and duplicate-review checks.', 'impact': 'Improved reporting accuracy and data integrity.', 'project_link': '', 'github_link': '', 'cover_image': '', 'gallery': []}, {'id': 'handwritten-document-digitization-system', 'title': 'Handwritten Document Digitization System', 'category': 'Automation', 'status': 'Published', 'featured': False, 'description': 'OCR and AI-assisted workflow for converting handwritten images and PDFs into structured Word or Excel outputs.', 'tools': ['Python', 'OCR', 'AI Extraction', 'Excel'], 'challenge': 'Handwritten information was difficult to digitize and reuse.', 'solution': 'Developed a conversion workflow combining OCR/AI extraction and structured output.', 'impact': 'Reduced manual retyping and improved accessibility of handwritten records.', 'project_link': '', 'github_link': '', 'cover_image': '', 'gallery': []}, {'id': 'football-match-prediction-dashboard', 'title': 'Football Match Prediction Dashboard', 'category': 'Data Analytics', 'status': 'Published', 'featured': False, 'description': 'Streamlit dashboard for analysing historical football data and presenting model-based match predictions.', 'tools': ['Python', 'Streamlit', 'Statistics', 'Data Analysis'], 'challenge': 'Historical match data needed to be collected, structured and presented in an accessible analytical interface.', 'solution': 'Built a Python and Streamlit workflow for analysis and dashboard presentation.', 'impact': 'Created a practical end-to-end analytics project combining data preparation, statistics and visualization.', 'project_link': '', 'github_link': '', 'cover_image': '', 'gallery': []}]

profile = read_json(PROFILE_FILE, DEFAULT_PROFILE)
projects = read_json(PROJECTS_FILE, DEFAULT_PROJECTS)
experience = read_json(EXPERIENCE_FILE, DEFAULT_EXPERIENCE)
skills = read_json(SKILLS_FILE, DEFAULT_SKILLS)
education = read_json(EDUCATION_FILE, DEFAULT_EDUCATION)
certifications = read_json(CERTIFICATIONS_FILE, DEFAULT_CERTIFICATIONS)
site_content = read_json(SITE_CONTENT_FILE, DEFAULT_SITE_CONTENT)

# If a JSON file exists but is empty, use the built-in portfolio baseline.
if not profile:
    profile = dict(DEFAULT_PROFILE)
if not projects:
    projects = list(DEFAULT_PROJECTS)
if not experience:
    experience = list(DEFAULT_EXPERIENCE)
if not skills:
    skills = dict(DEFAULT_SKILLS)
if not education:
    education = list(DEFAULT_EDUCATION)
if not certifications:
    certifications = list(DEFAULT_CERTIFICATIONS)

# Automatically add any newly introduced content settings without removing
# values the Admin has already customized.
site_content = {**DEFAULT_SITE_CONTENT, **site_content}

def content(key, default=""):
    value = site_content.get(key, default)
    return str(value) if value is not None else ""

def live_url(value):
    """Return a safe external URL or an empty string."""
    value = str(value or "").strip()
    if value.startswith("https://") or value.startswith("http://"):
        return value
    return ""

# ---------- Styling ----------
st.markdown("""
<style>
:root {
    --navy:#102A43;
    --ink:#233548;
    --muted:#65758B;
    --teal:#0F766E;
    --teal-soft:#EAF7F4;
    --soft:#F4F7FB;
    --page:#F7F9FC;
    --white:#FFFFFF;
    --line:#E3E9F1;
    --shadow:0 12px 34px rgba(16,42,67,.08);
}

html, body, [class*="css"] {
    font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
}

.stApp {
    background:
      radial-gradient(circle at 8% 0%, rgba(15,118,110,.08), transparent 26rem),
      radial-gradient(circle at 93% 7%, rgba(45,105,175,.07), transparent 27rem),
      var(--page);
    color: var(--ink);
}

[data-testid="stHeader"] {
    background: rgba(247,249,252,.90);
    backdrop-filter: blur(12px);
}

.block-container {
    max-width: 1180px;
    padding-top: 1.05rem;
    padding-bottom: 4rem;
}

/* Top navigation */
div[role="radiogroup"] {
    background: rgba(255,255,255,.95);
    border: 1px solid var(--line);
    border-radius: 999px;
    padding: .34rem .55rem;
    box-shadow: 0 8px 24px rgba(16,42,67,.06);
    gap: .12rem;
    position: sticky;
    top: .45rem;
    z-index: 100;
}

div[role="radiogroup"] label {
    border-radius: 999px;
    padding: .2rem .3rem;
}

/* Hero */
.hero-wrap {
    background: linear-gradient(135deg, rgba(255,255,255,.98), rgba(238,245,255,.90));
    border: 1px solid var(--line);
    border-radius: 28px;
    padding: clamp(1.6rem, 4vw, 3.1rem);
    margin-top: 1.2rem;
    box-shadow: var(--shadow);
}

.eyebrow {
    color: var(--teal);
    text-transform: uppercase;
    letter-spacing: .14em;
    font-size: .74rem;
    font-weight: 800;
}

.hero-name {
    color: var(--navy);
    font-size: clamp(3.1rem, 7.4vw, 6.2rem);
    line-height: .96;
    letter-spacing: -.058em;
    font-weight: 850;
    margin: .45rem 0 1rem;
}

.hero-title {
    color: var(--ink);
    font-size: clamp(1.45rem, 3vw, 2.45rem);
    line-height: 1.14;
    letter-spacing: -.035em;
    font-weight: 720;
    max-width: 850px;
    margin-bottom: 1.05rem;
}

.hero-copy {
    max-width: 790px;
    color: var(--muted);
    font-size: 1.06rem;
    line-height: 1.82;
}

.profile-placeholder {
    width: 100%;
    min-height: 270px;
    border-radius: 28px;
    background: linear-gradient(145deg,#E7F2F7,#F9FBFD);
    border: 1px solid var(--line);
    display:flex;
    align-items:center;
    justify-content:center;
    font-size:4.25rem;
    font-weight:850;
    color:var(--navy);
    box-shadow:var(--shadow);
}

.section-shell { padding: 3rem 0 .75rem; }
.section-title {
    color: var(--navy);
    font-size: clamp(2rem, 4vw, 3.05rem);
    line-height:1.07;
    letter-spacing: -.045em;
    font-weight: 820;
    margin: .3rem 0 .55rem;
}
.section-copy {
    color: var(--muted);
    max-width: 780px;
    font-size: 1rem;
    line-height: 1.75;
}

/* Streamlit bordered containers become polished cards */
div[data-testid="stVerticalBlockBorderWrapper"] {
    border-color: var(--line) !important;
    border-radius: 20px !important;
    background: rgba(255,255,255,.97) !important;
    box-shadow: 0 8px 28px rgba(16,42,67,.05);
}

.project-card {
    background:#fff;
    border:1px solid var(--line);
    border-radius:20px;
    padding:1rem;
    min-height:100%;
    box-shadow:0 8px 28px rgba(16,42,67,.05);
}

.project-cover {
    background: linear-gradient(135deg,#EAF7F4,#EEF5FF);
    border:1px solid #DCE7F0;
    border-radius:15px;
    min-height:180px;
    display:flex;
    align-items:center;
    justify-content:center;
    color:#6E7E91;
    margin-bottom:1rem;
    text-align:center;
    padding:1rem;
    font-weight:650;
}

.project-cat {
    color:var(--teal);
    font-size:.70rem;
    text-transform:uppercase;
    letter-spacing:.10em;
    font-weight:850;
}
.project-title {
    color:var(--navy);
    font-size:1.17rem;
    line-height:1.28;
    font-weight:800;
    margin:.35rem 0 .45rem;
}
.project-desc {
    color:var(--muted);
    line-height:1.62;
    font-size:.93rem;
    min-height:70px;
}
.tool-pill {
    display:inline-block;
    border:1px solid #E0E7EF;
    background:#F1F5F9;
    border-radius:999px;
    padding:.29rem .53rem;
    margin:.17rem .17rem .1rem 0;
    color:#506176;
    font-size:.72rem;
    font-weight:650;
}

.info-card,
.admin-card {
    border:1px solid var(--line);
    border-radius:20px;
    padding:1.25rem;
    background:#fff;
    box-shadow:0 8px 28px rgba(16,42,67,.05);
}

.muted { color:var(--muted); }

[data-testid="stImage"] img {
    border-radius:18px;
    box-shadow:0 8px 24px rgba(16,42,67,.07);
}

/* Inputs and buttons */
div[data-testid="stButton"] > button,
div[data-testid="stDownloadButton"] > button,
div[data-testid="stLinkButton"] > a {
    border-radius:999px !important;
    min-height:2.65rem;
    font-weight:700 !important;
}

[data-baseweb="input"] > div,
[data-baseweb="textarea"] > div,
[data-baseweb="select"] > div {
    border-radius:12px !important;
}

.footer {
    margin-top:4rem;
    padding-top:1.5rem;
    border-top:1px solid var(--line);
    color:var(--muted);
    font-size:.84rem;
}

@media (max-width: 700px) {
    .block-container { padding-left:1rem; padding-right:1rem; }
    .hero-wrap { border-radius:20px; padding:1.35rem; }
    div[role="radiogroup"] { overflow-x:auto; flex-wrap:nowrap; }
    .project-desc { min-height:0; }
}

/* --- Professional navigation: hide Streamlit radio circles --- */
div[data-testid="stRadio"] > div {
    gap: .15rem !important;
}

div[data-testid="stRadio"] div[role="radiogroup"] {
    display: flex !important;
    align-items: center !important;
    justify-content: center !important;
    flex-wrap: wrap !important;
    background: rgba(255,255,255,.96) !important;
    border: 1px solid var(--line) !important;
    border-radius: 16px !important;
    padding: .42rem .55rem !important;
    box-shadow: 0 8px 24px rgba(16,42,67,.06) !important;
    position: sticky !important;
    top: .55rem !important;
    z-index: 100 !important;
}

/* Hide the native radio control/circle */
div[data-testid="stRadio"] div[role="radiogroup"] label > div:first-child {
    display: none !important;
}

/* Menu item */
div[data-testid="stRadio"] div[role="radiogroup"] label {
    cursor: pointer !important;
    padding: .62rem .88rem !important;
    border-radius: 10px !important;
    transition: all .18s ease !important;
    margin: 0 !important;
    min-height: auto !important;
}

div[data-testid="stRadio"] div[role="radiogroup"] label p {
    color: #506176 !important;
    font-size: .91rem !important;
    font-weight: 650 !important;
    margin: 0 !important;
    line-height: 1 !important;
}

/* Hover */
div[data-testid="stRadio"] div[role="radiogroup"] label:hover {
    background: #F1F5F9 !important;
}

div[data-testid="stRadio"] div[role="radiogroup"] label:hover p {
    color: var(--navy) !important;
}

/* Active item */
div[data-testid="stRadio"] div[role="radiogroup"] label:has(input:checked) {
    background: var(--navy) !important;
    box-shadow: 0 4px 12px rgba(16,42,67,.16) !important;
}

div[data-testid="stRadio"] div[role="radiogroup"] label:has(input:checked) p {
    color: #FFFFFF !important;
}

/* Slightly tighter mobile menu */
@media (max-width: 700px) {
    div[data-testid="stRadio"] div[role="radiogroup"] {
        justify-content: flex-start !important;
        overflow-x: auto !important;
        flex-wrap: nowrap !important;
        border-radius: 14px !important;
    }

    div[data-testid="stRadio"] div[role="radiogroup"] label {
        flex: 0 0 auto !important;
        padding: .56rem .72rem !important;
    }
}


/* --- Fix Streamlit header covering navigation --- */

/* Hide Streamlit's top chrome so it cannot overlap the portfolio menu */
[data-testid="stHeader"] {
    display: none !important;
}

[data-testid="stToolbar"],
[data-testid="stDecoration"],
[data-testid="stStatusWidget"] {
    display: none !important;
}

/* Give the page comfortable breathing room at the top */
.block-container {
    padding-top: 1.4rem !important;
}

/* Keep navigation fully visible */
div[data-testid="stRadio"] {
    margin-top: .4rem !important;
    margin-bottom: 1.2rem !important;
}

div[data-testid="stRadio"] div[role="radiogroup"] {
    position: sticky !important;
    top: .75rem !important;
    z-index: 9999 !important;
    overflow: visible !important;
}

/* Ensure labels/text are never clipped */
div[data-testid="stRadio"] div[role="radiogroup"] label {
    overflow: visible !important;
    min-height: 2.6rem !important;
    display: flex !important;
    align-items: center !important;
}

div[data-testid="stRadio"] div[role="radiogroup"] label p {
    overflow: visible !important;
    line-height: 1.2 !important;
}


/* --- Single-row navigation alignment --- */
div[data-testid="stRadio"] {
    margin-top: 0 !important;
    margin-bottom: 1rem !important;
}

div[data-testid="stRadio"] div[role="radiogroup"] {
    width: 100% !important;
    display: flex !important;
    flex-wrap: nowrap !important;
    align-items: center !important;
    justify-content: space-between !important;
    min-height: 3.6rem !important;
    padding: .38rem .45rem !important;
    top: .7rem !important;
}

div[data-testid="stRadio"] div[role="radiogroup"] label {
    flex: 1 1 0 !important;
    min-width: 0 !important;
    min-height: 2.8rem !important;
    padding: .55rem .45rem !important;
    display: flex !important;
    align-items: center !important;
    justify-content: center !important;
}

div[data-testid="stRadio"] div[role="radiogroup"] label p {
    width: 100% !important;
    text-align: center !important;
    white-space: nowrap !important;
    line-height: 1.2 !important;
    font-size: .90rem !important;
    overflow: visible !important;
}

/* Top Admin button: one clean button aligned with the menu */
div[data-testid="stButton"] button[kind="secondary"] {
    min-height: 3.05rem;
}

@media (max-width: 800px) {
    div[data-testid="stRadio"] div[role="radiogroup"] {
        overflow-x: auto !important;
        justify-content: flex-start !important;
    }

    div[data-testid="stRadio"] div[role="radiogroup"] label {
        flex: 0 0 auto !important;
        min-width: 6.1rem !important;
        padding-left: .7rem !important;
        padding-right: .7rem !important;
    }
}


/* --- Refined hero alignment --- */
.hero-wrap {
    display: none !important;
}

.hero-content {
    padding: 1.15rem 0 .5rem 0;
}

.hero-content .eyebrow {
    max-width: 760px;
    line-height: 1.55;
    margin-bottom: .65rem;
}

.hero-name {
    font-size: clamp(3.25rem, 6.2vw, 5.15rem) !important;
    line-height: .96 !important;
    letter-spacing: -.052em !important;
    margin: .15rem 0 .85rem !important;
}

.hero-title {
    font-size: clamp(1.55rem, 2.55vw, 2.25rem) !important;
    line-height: 1.18 !important;
    max-width: 800px !important;
    margin-bottom: .9rem !important;
}

.hero-copy {
    max-width: 820px !important;
    font-size: 1.02rem !important;
    line-height: 1.7 !important;
}

.profile-placeholder {
    min-height: 320px !important;
    border-radius: 26px !important;
}

.professional-strip {
    margin: 1.35rem 0 .7rem;
    display: grid;
    grid-template-columns: 1.35fr 1.25fr .75fr 1.15fr;
    background: rgba(255,255,255,.95);
    border: 1px solid var(--line);
    border-radius: 20px;
    box-shadow: 0 8px 24px rgba(16,42,67,.05);
    overflow: hidden;
}

.snapshot-item {
    padding: 1rem 1.1rem;
    border-right: 1px solid var(--line);
    min-height: 78px;
    display: flex;
    flex-direction: column;
    justify-content: center;
}

.snapshot-item:last-child {
    border-right: none;
}

.snapshot-label {
    color: var(--teal);
    text-transform: uppercase;
    letter-spacing: .09em;
    font-size: .66rem;
    font-weight: 800;
    margin-bottom: .28rem;
}

.snapshot-value {
    color: var(--navy);
    font-size: .92rem;
    line-height: 1.35;
    font-weight: 750;
}

@media (max-width: 900px) {
    .professional-strip {
        grid-template-columns: 1fr 1fr;
    }
    .snapshot-item:nth-child(2) {
        border-right: none;
    }
    .snapshot-item:nth-child(-n+2) {
        border-bottom: 1px solid var(--line);
    }
}

@media (max-width: 650px) {
    .professional-strip {
        grid-template-columns: 1fr;
    }
    .snapshot-item {
        border-right: none !important;
        border-bottom: 1px solid var(--line);
    }
    .snapshot-item:last-child {
        border-bottom: none;
    }
    .profile-placeholder {
        min-height: 250px !important;
    }
}


/* --- Consistent text/block alignment across the portfolio --- */

/* Long-form descriptive text: clean straight left/right edges */
.hero-copy,
.section-copy,
.project-desc,
.info-card p,
.admin-card p,
div[data-testid="stMarkdownContainer"] > p {
    text-align: justify !important;
    text-justify: inter-word !important;
    hyphens: auto;
}

/* Keep headings, labels and short UI text naturally left aligned */
.hero-name,
.hero-title,
.eyebrow,
.section-title,
.project-title,
.project-cat,
.snapshot-label,
.snapshot-value,
h1, h2, h3, h4,
label,
button,
[data-testid="stCaptionContainer"],
div[data-testid="stMarkdownContainer"] strong {
    text-align: left !important;
}

/* Consistent paragraph width and rhythm */
.hero-copy,
.section-copy {
    max-width: 100% !important;
    line-height: 1.72 !important;
    margin-bottom: .6rem !important;
}

div[data-testid="stMarkdownContainer"] > p {
    line-height: 1.68 !important;
    margin-top: .15rem !important;
    margin-bottom: .7rem !important;
}

/* Keep cards/blocks visually aligned */
div[data-testid="stVerticalBlockBorderWrapper"] {
    height: 100%;
}

.project-card,
.info-card,
.admin-card {
    height: 100%;
}

/* Better alignment inside experience / education / skills cards */
div[data-testid="stVerticalBlockBorderWrapper"] p {
    margin-bottom: .45rem !important;
}

/* Mobile: avoid awkward word spacing on narrow screens */
@media (max-width: 700px) {
    .hero-copy,
    .section-copy,
    .project-desc,
    .info-card p,
    .admin-card p,
    div[data-testid="stMarkdownContainer"] > p {
        text-align: left !important;
        hyphens: none;
    }
}


/* --- Admin save/action feedback --- */
div[data-testid="stAlert"] {
    border-radius: 14px !important;
    border-width: 1px !important;
    margin: .55rem 0 1rem !important;
}

div[data-testid="stAlert"] p {
    text-align: left !important;
    margin: 0 !important;
    font-weight: 650 !important;
}

/* Save buttons feel more deliberate */
button[kind="primaryFormSubmit"],
button[kind="secondaryFormSubmit"] {
    font-weight: 750 !important;
}


/* --- Clean website navigation: button based, no radio circles --- */
div[data-testid="stHorizontalBlock"]:has(button[id*="nav_btn_"]) {
    background: rgba(255,255,255,.96);
    border: 1px solid var(--line);
    border-radius: 18px;
    padding: .38rem;
    box-shadow: 0 8px 24px rgba(16,42,67,.06);
}

button[id*="nav_btn_"] {
    border-radius: 12px !important;
    border: 0 !important;
    min-height: 2.75rem !important;
    font-weight: 700 !important;
    box-shadow: none !important;
}

button[id*="nav_btn_"][kind="secondary"] {
    background: transparent !important;
    color: #506176 !important;
}

button[id*="nav_btn_"][kind="secondary"]:hover {
    background: #F1F5F9 !important;
    color: var(--navy) !important;
}

button[id*="nav_btn_"][kind="primary"] {
    background: var(--navy) !important;
    color: #FFFFFF !important;
}

@media (max-width: 800px) {
    div[data-testid="stHorizontalBlock"]:has(button[id*="nav_btn_"]) {
        overflow-x: auto !important;
        flex-wrap: nowrap !important;
    }
}


/* =========================================================
   CROSS-DEVICE VISIBILITY + RESPONSIVE CONTRAST
   Phone / Android / iPhone / Tablet / Laptop / Desktop
   ========================================================= */

/* Tell mobile browsers not to auto-darken the light portfolio theme. */
html, body, .stApp {
    color-scheme: light !important;
}

.stApp {
    background-color: #F7F9FC !important;
    color: #233548 !important;
}

/* Keep ordinary Streamlit text readable even when a device/browser
   prefers dark mode. */
.stApp p,
.stApp li,
.stApp label,
.stApp small,
.stApp [data-testid="stCaptionContainer"],
.stApp [data-testid="stMarkdownContainer"] {
    color: #233548;
}

/* ---------- ALL BUTTONS: explicit accessible contrast ---------- */
div[data-testid="stButton"] > button,
div[data-testid="stDownloadButton"] > button,
div[data-testid="stLinkButton"] > a,
button[data-testid^="stBaseButton"] {
    border: 1px solid #D6E0EA !important;
    background: #FFFFFF !important;
    color: #102A43 !important;
    -webkit-text-fill-color: #102A43 !important;
    opacity: 1 !important;
    box-shadow: none !important;
}

div[data-testid="stButton"] > button *,
div[data-testid="stDownloadButton"] > button *,
div[data-testid="stLinkButton"] > a *,
button[data-testid^="stBaseButton"] * {
    color: inherit !important;
    -webkit-text-fill-color: currentColor !important;
    opacity: 1 !important;
}

/* Primary action buttons */
div[data-testid="stButton"] > button[kind="primary"],
div[data-testid="stDownloadButton"] > button[kind="primary"],
button[data-testid="stBaseButton-primary"],
button[kind="primaryFormSubmit"] {
    background: #102A43 !important;
    border-color: #102A43 !important;
    color: #FFFFFF !important;
    -webkit-text-fill-color: #FFFFFF !important;
}

/* Secondary / normal action buttons */
div[data-testid="stButton"] > button[kind="secondary"],
button[data-testid="stBaseButton-secondary"],
button[kind="secondaryFormSubmit"] {
    background: #FFFFFF !important;
    border-color: #CFD9E5 !important;
    color: #102A43 !important;
    -webkit-text-fill-color: #102A43 !important;
}

/* Hover/focus visible on pointer devices and keyboards */
div[data-testid="stButton"] > button:hover,
div[data-testid="stDownloadButton"] > button:hover,
div[data-testid="stLinkButton"] > a:hover {
    border-color: #0F766E !important;
    color: #0F766E !important;
    -webkit-text-fill-color: #0F766E !important;
}

div[data-testid="stButton"] > button[kind="primary"]:hover,
button[data-testid="stBaseButton-primary"]:hover {
    background: #0B5E59 !important;
    border-color: #0B5E59 !important;
    color: #FFFFFF !important;
    -webkit-text-fill-color: #FFFFFF !important;
}

div[data-testid="stButton"] > button:focus-visible,
div[data-testid="stDownloadButton"] > button:focus-visible,
div[data-testid="stLinkButton"] > a:focus-visible {
    outline: 3px solid rgba(15,118,110,.28) !important;
    outline-offset: 2px !important;
}

/* ---------- TOP NAVIGATION ---------- */
/* Streamlit adds a class based on widget key. This targets all six menu buttons. */
[class*="st-key-nav_btn_"] button {
    min-height: 2.8rem !important;
    border-radius: 11px !important;
    font-size: .92rem !important;
    font-weight: 750 !important;
}

/* Inactive navigation */
[class*="st-key-nav_btn_"] button[kind="secondary"],
[class*="st-key-nav_btn_"] button[data-testid="stBaseButton-secondary"] {
    background: #FFFFFF !important;
    color: #334E68 !important;
    -webkit-text-fill-color: #334E68 !important;
    border: 1px solid #D8E1EA !important;
}

/* Active navigation */
[class*="st-key-nav_btn_"] button[kind="primary"],
[class*="st-key-nav_btn_"] button[data-testid="stBaseButton-primary"] {
    background: #102A43 !important;
    color: #FFFFFF !important;
    -webkit-text-fill-color: #FFFFFF !important;
    border: 1px solid #102A43 !important;
}

/* Admin button */
.st-key-open_admin_top button {
    background: #FFFFFF !important;
    color: #102A43 !important;
    -webkit-text-fill-color: #102A43 !important;
    border: 1px solid #BCCBDD !important;
    font-weight: 750 !important;
}

/* Force the menu's Streamlit columns to remain a deliberate grid instead
   of becoming one huge vertical button per row on phones. */
div[data-testid="stHorizontalBlock"]:has([class*="st-key-nav_btn_"]) {
    display: grid !important;
    grid-template-columns: repeat(6, minmax(0, 1fr)) !important;
    gap: .35rem !important;
    background: #FFFFFF !important;
    border: 1px solid #DCE5EE !important;
    border-radius: 18px !important;
    padding: .38rem !important;
    box-shadow: 0 8px 24px rgba(16,42,67,.06) !important;
}

div[data-testid="stHorizontalBlock"]:has([class*="st-key-nav_btn_"]) > div[data-testid="stColumn"] {
    width: 100% !important;
    min-width: 0 !important;
    flex: none !important;
}

/* ---------- ADMIN TABS ---------- */
div[data-baseweb="tab-list"] {
    background: #FFFFFF !important;
    border: 1px solid #DCE5EE !important;
    border-radius: 14px !important;
    padding: .28rem !important;
    gap: .16rem !important;
}

button[data-baseweb="tab"] {
    background: #FFFFFF !important;
    color: #334E68 !important;
    -webkit-text-fill-color: #334E68 !important;
    opacity: 1 !important;
    border-radius: 9px !important;
    font-weight: 700 !important;
    min-height: 2.55rem !important;
}

button[data-baseweb="tab"] *,
button[data-baseweb="tab"] p,
button[data-baseweb="tab"] span {
    color: inherit !important;
    -webkit-text-fill-color: currentColor !important;
    opacity: 1 !important;
}

button[data-baseweb="tab"][aria-selected="true"] {
    background: #EAF7F4 !important;
    color: #0B625C !important;
    -webkit-text-fill-color: #0B625C !important;
}

/* Tab overflow arrows remain clearly visible on narrow screens */
div[data-baseweb="tab-list"] button[aria-label*="scroll" i],
div[data-baseweb="tab-list"] button[aria-label*="previous" i],
div[data-baseweb="tab-list"] button[aria-label*="next" i] {
    background: #102A43 !important;
    color: #FFFFFF !important;
    -webkit-text-fill-color: #FFFFFF !important;
}

/* ---------- DASHBOARD METRICS ---------- */
[data-testid="stMetric"] {
    background: #FFFFFF !important;
    border: 1px solid #DCE5EE !important;
    border-radius: 16px !important;
    padding: .85rem 1rem !important;
}

[data-testid="stMetricLabel"],
[data-testid="stMetricLabel"] *,
[data-testid="stMetricValue"],
[data-testid="stMetricValue"] *,
[data-testid="stMetricDelta"],
[data-testid="stMetricDelta"] * {
    color: #102A43 !important;
    -webkit-text-fill-color: #102A43 !important;
    opacity: 1 !important;
}

[data-testid="stMetricValue"] {
    font-weight: 800 !important;
}

/* ---------- INPUTS / FORMS ---------- */
input,
textarea,
[data-baseweb="select"] > div,
[data-baseweb="input"] > div,
[data-baseweb="textarea"] > div {
    background: #FFFFFF !important;
    color: #233548 !important;
    -webkit-text-fill-color: #233548 !important;
}

input::placeholder,
textarea::placeholder {
    color: #74869A !important;
    -webkit-text-fill-color: #74869A !important;
    opacity: 1 !important;
}

/* ---------- CARDS / EXPANDERS ---------- */
div[data-testid="stVerticalBlockBorderWrapper"],
div[data-testid="stExpander"] {
    background: #FFFFFF !important;
    color: #233548 !important;
}

details summary,
details summary *,
[data-testid="stExpander"] summary,
[data-testid="stExpander"] summary * {
    color: #102A43 !important;
    -webkit-text-fill-color: #102A43 !important;
    opacity: 1 !important;
}

/* ---------- MOBILE / TABLET ---------- */
@media (max-width: 900px) {
    .block-container {
        padding-left: .85rem !important;
        padding-right: .85rem !important;
        padding-top: .75rem !important;
    }

    /* Two rows of three menu buttons on tablets/small screens. */
    div[data-testid="stHorizontalBlock"]:has([class*="st-key-nav_btn_"]) {
        grid-template-columns: repeat(3, minmax(0, 1fr)) !important;
    }

    [class*="st-key-nav_btn_"] button {
        min-height: 2.72rem !important;
        font-size: .88rem !important;
    }

    /* Admin tabs scroll horizontally rather than becoming unreadable. */
    div[data-baseweb="tab-list"] {
        overflow-x: auto !important;
        flex-wrap: nowrap !important;
        scrollbar-width: thin !important;
    }

    button[data-baseweb="tab"] {
        flex: 0 0 auto !important;
        white-space: nowrap !important;
        padding-left: .75rem !important;
        padding-right: .75rem !important;
    }

    .hero-name {
        font-size: clamp(2.75rem, 11vw, 4.2rem) !important;
        overflow-wrap: anywhere !important;
    }

    .hero-title {
        font-size: clamp(1.35rem, 5.8vw, 2rem) !important;
    }

    .hero-copy,
    .section-copy {
        font-size: .98rem !important;
        line-height: 1.62 !important;
    }
}

@media (max-width: 520px) {
    /* Two columns keeps phone navigation compact and readable. */
    div[data-testid="stHorizontalBlock"]:has([class*="st-key-nav_btn_"]) {
        grid-template-columns: repeat(2, minmax(0, 1fr)) !important;
        gap: .3rem !important;
        border-radius: 14px !important;
    }

    [class*="st-key-nav_btn_"] button {
        min-height: 2.65rem !important;
        font-size: .85rem !important;
        padding-left: .35rem !important;
        padding-right: .35rem !important;
    }

    .professional-strip {
        border-radius: 14px !important;
    }

    .snapshot-item {
        padding: .85rem .9rem !important;
    }

    .section-shell {
        padding-top: 2rem !important;
    }

    .section-title {
        font-size: clamp(1.75rem, 8.8vw, 2.35rem) !important;
        overflow-wrap: anywhere !important;
    }

    /* Mobile buttons should never use black backgrounds with dark text. */
    div[data-testid="stButton"] > button[kind="secondary"],
    button[data-testid="stBaseButton-secondary"],
    div[data-testid="stLinkButton"] > a,
    div[data-testid="stDownloadButton"] > button {
        background: #FFFFFF !important;
        color: #102A43 !important;
        -webkit-text-fill-color: #102A43 !important;
    }

    div[data-testid="stButton"] > button[kind="primary"],
    button[data-testid="stBaseButton-primary"] {
        background: #102A43 !important;
        color: #FFFFFF !important;
        -webkit-text-fill-color: #FFFFFF !important;
    }
}


/* =========================================================
   FINAL STABLE RESPONSIVE NAVIGATION
   Desktop / Laptop / Tablet / Android / iPhone
   ========================================================= */

html, body, .stApp {
    color-scheme: light !important;
}

.stApp {
    background: #F7F9FC !important;
    color: #233548 !important;
}

/* Keep public text readable regardless of device dark-mode preference. */
.stApp p,
.stApp li,
.stApp label,
.stApp small,
.stApp h1,
.stApp h2,
.stApp h3,
.stApp h4,
.stApp [data-testid="stCaptionContainer"] {
    opacity: 1 !important;
}

/* ---------- TOP MENU ---------- */
div[data-testid="stRadio"] {
    width: 100% !important;
    margin: 0 !important;
}

div[data-testid="stRadio"] > div[role="radiogroup"] {
    width: 100% !important;
    display: flex !important;
    flex-direction: row !important;
    flex-wrap: nowrap !important;
    align-items: center !important;
    justify-content: stretch !important;
    gap: .32rem !important;
    overflow-x: auto !important;
    scrollbar-width: none !important;
    background: #FFFFFF !important;
    border: 1px solid #D9E3ED !important;
    border-radius: 18px !important;
    padding: .38rem !important;
    box-shadow: 0 8px 24px rgba(16,42,67,.06) !important;
}

div[data-testid="stRadio"] > div[role="radiogroup"]::-webkit-scrollbar {
    display: none !important;
}

/* Completely hide native radio circles without hiding the label text. */
div[data-testid="stRadio"] > div[role="radiogroup"] label > div:first-child {
    display: none !important;
}

div[data-testid="stRadio"] > div[role="radiogroup"] label {
    flex: 1 1 0 !important;
    min-width: 6.6rem !important;
    min-height: 2.8rem !important;
    display: flex !important;
    align-items: center !important;
    justify-content: center !important;
    border-radius: 11px !important;
    padding: .55rem .68rem !important;
    margin: 0 !important;
    background: #FFFFFF !important;
    border: 1px solid transparent !important;
    cursor: pointer !important;
    opacity: 1 !important;
}

div[data-testid="stRadio"] > div[role="radiogroup"] label p {
    display: block !important;
    visibility: visible !important;
    opacity: 1 !important;
    width: auto !important;
    margin: 0 !important;
    padding: 0 !important;
    color: #334E68 !important;
    -webkit-text-fill-color: #334E68 !important;
    font-size: .91rem !important;
    font-weight: 720 !important;
    line-height: 1.2 !important;
    text-align: center !important;
    white-space: nowrap !important;
}

/* Active page */
div[data-testid="stRadio"] > div[role="radiogroup"] label:has(input:checked) {
    background: #102A43 !important;
    border-color: #102A43 !important;
    box-shadow: 0 4px 12px rgba(16,42,67,.16) !important;
}

div[data-testid="stRadio"] > div[role="radiogroup"] label:has(input:checked) p {
    color: #FFFFFF !important;
    -webkit-text-fill-color: #FFFFFF !important;
}

/* Hover */
div[data-testid="stRadio"] > div[role="radiogroup"] label:hover:not(:has(input:checked)) {
    background: #EEF4F8 !important;
    border-color: #D6E0EA !important;
}

div[data-testid="stRadio"] > div[role="radiogroup"] label:hover:not(:has(input:checked)) p {
    color: #102A43 !important;
    -webkit-text-fill-color: #102A43 !important;
}

/* Admin button */
.st-key-open_admin_top button,
div[data-testid="stButton"] .st-key-open_admin_top button {
    min-height: 3rem !important;
    background: #FFFFFF !important;
    color: #102A43 !important;
    -webkit-text-fill-color: #102A43 !important;
    border: 1px solid #BCCBDD !important;
    border-radius: 12px !important;
    font-weight: 750 !important;
}

.st-key-open_admin_top button *,
div[data-testid="stButton"] .st-key-open_admin_top button * {
    color: inherit !important;
    -webkit-text-fill-color: currentColor !important;
    opacity: 1 !important;
}

/* ---------- ADMIN TABS ---------- */
div[data-baseweb="tab-list"] {
    background: #FFFFFF !important;
    border: 1px solid #DCE5EE !important;
    border-radius: 14px !important;
    padding: .28rem !important;
    gap: .16rem !important;
    overflow-x: auto !important;
    flex-wrap: nowrap !important;
    scrollbar-width: thin !important;
}

button[data-baseweb="tab"] {
    flex: 0 0 auto !important;
    white-space: nowrap !important;
    min-height: 2.55rem !important;
    padding: .45rem .8rem !important;
    background: #FFFFFF !important;
    color: #334E68 !important;
    -webkit-text-fill-color: #334E68 !important;
    opacity: 1 !important;
    border-radius: 9px !important;
    font-weight: 700 !important;
}

button[data-baseweb="tab"] *,
button[data-baseweb="tab"] p,
button[data-baseweb="tab"] span {
    color: inherit !important;
    -webkit-text-fill-color: currentColor !important;
    opacity: 1 !important;
}

button[data-baseweb="tab"][aria-selected="true"] {
    background: #EAF7F4 !important;
    color: #0B625C !important;
    -webkit-text-fill-color: #0B625C !important;
}

/* ---------- GENERAL CONTROLS ---------- */
div[data-testid="stButton"] > button,
div[data-testid="stDownloadButton"] > button,
div[data-testid="stLinkButton"] > a {
    opacity: 1 !important;
}

div[data-testid="stButton"] > button[kind="secondary"],
div[data-testid="stDownloadButton"] > button,
div[data-testid="stLinkButton"] > a {
    background: #FFFFFF !important;
    color: #102A43 !important;
    -webkit-text-fill-color: #102A43 !important;
    border-color: #CFD9E5 !important;
}

div[data-testid="stButton"] > button[kind="secondary"] *,
div[data-testid="stDownloadButton"] > button *,
div[data-testid="stLinkButton"] > a * {
    color: inherit !important;
    -webkit-text-fill-color: currentColor !important;
    opacity: 1 !important;
}

div[data-testid="stButton"] > button[kind="primary"] {
    background: #102A43 !important;
    color: #FFFFFF !important;
    -webkit-text-fill-color: #FFFFFF !important;
    border-color: #102A43 !important;
}

div[data-testid="stButton"] > button[kind="primary"] * {
    color: #FFFFFF !important;
    -webkit-text-fill-color: #FFFFFF !important;
}

/* Metrics */
[data-testid="stMetric"] {
    background: #FFFFFF !important;
    border: 1px solid #DCE5EE !important;
    border-radius: 16px !important;
    padding: .85rem 1rem !important;
}

[data-testid="stMetricLabel"],
[data-testid="stMetricLabel"] *,
[data-testid="stMetricValue"],
[data-testid="stMetricValue"] * {
    color: #102A43 !important;
    -webkit-text-fill-color: #102A43 !important;
    opacity: 1 !important;
}

/* Forms */
input,
textarea,
[data-baseweb="select"] > div,
[data-baseweb="input"] > div,
[data-baseweb="textarea"] > div {
    background: #FFFFFF !important;
    color: #233548 !important;
    -webkit-text-fill-color: #233548 !important;
}

/* ---------- TABLET ---------- */
@media (max-width: 900px) {
    .block-container {
        padding-left: .9rem !important;
        padding-right: .9rem !important;
    }

    div[data-testid="stRadio"] > div[role="radiogroup"] label {
        flex: 0 0 auto !important;
        min-width: 7rem !important;
    }

    .hero-name {
        font-size: clamp(2.8rem, 10vw, 4.3rem) !important;
        overflow-wrap: anywhere !important;
    }
}

/* ---------- PHONE ---------- */
@media (max-width: 600px) {
    .block-container {
        padding-left: .75rem !important;
        padding-right: .75rem !important;
        padding-top: .65rem !important;
    }

    /* Horizontal scroll is more compact and reliable than giant stacked buttons. */
    div[data-testid="stRadio"] > div[role="radiogroup"] {
        justify-content: flex-start !important;
        border-radius: 14px !important;
        padding: .3rem !important;
        gap: .25rem !important;
    }

    div[data-testid="stRadio"] > div[role="radiogroup"] label {
        flex: 0 0 auto !important;
        min-width: 6.35rem !important;
        min-height: 2.55rem !important;
        padding: .48rem .55rem !important;
    }

    div[data-testid="stRadio"] > div[role="radiogroup"] label p {
        font-size: .84rem !important;
    }

    .hero-name {
        font-size: clamp(2.45rem, 12vw, 3.65rem) !important;
        line-height: .98 !important;
    }

    .hero-title {
        font-size: clamp(1.25rem, 6vw, 1.8rem) !important;
    }

    .section-title {
        font-size: clamp(1.7rem, 9vw, 2.25rem) !important;
    }
}


/* =========================================================
   CENTERED PROFILE HERO
   Profile image -> Name -> Social links -> Professional text
   ========================================================= */

.center-hero {
    width: min(920px, 100%);
    margin: 1.5rem auto 1.1rem;
    padding: clamp(1.5rem, 4vw, 2.6rem) clamp(1rem, 4vw, 2.6rem);
    text-align: center;
    background: rgba(255,255,255,.72);
    border: 1px solid #E0E8F0;
    border-radius: 28px;
    box-shadow: 0 14px 38px rgba(16,42,67,.07);
}

.center-profile-visual {
    display: flex;
    justify-content: center;
    align-items: center;
    margin: 0 auto .95rem;
}

.center-profile-photo,
.center-profile-initials {
    width: clamp(150px, 17vw, 205px);
    height: clamp(150px, 17vw, 205px);
    border-radius: 50%;
    border: 5px solid #FFFFFF;
    box-shadow: 0 12px 30px rgba(16,42,67,.15);
}

.center-profile-photo {
    display: block;
    object-fit: cover;
    object-position: center;
    background: #EEF4F8;
}

.center-profile-initials {
    display: flex;
    align-items: center;
    justify-content: center;
    background: linear-gradient(145deg,#E7F2F7,#F9FBFD);
    color: #102A43;
    font-size: clamp(2.8rem, 6vw, 4.4rem);
    font-weight: 850;
}

.center-profile-name {
    color: #102A43;
    font-size: clamp(2.7rem, 6vw, 4.9rem);
    line-height: 1;
    letter-spacing: -.052em;
    font-weight: 850;
    margin: .25rem auto .75rem;
}

.center-profile-socials {
    display: flex;
    justify-content: center;
    align-items: center;
    flex-wrap: wrap;
    gap: .6rem;
    margin: 0 auto 1rem;
}

.profile-social-link {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    min-height: 2.55rem;
    padding: .58rem 1rem;
    border-radius: 999px;
    border: 1px solid #CCD8E4;
    background: #FFFFFF;
    color: #102A43 !important;
    text-decoration: none !important;
    font-size: .9rem;
    font-weight: 750;
    line-height: 1;
    transition: .18s ease;
}

.profile-social-link:hover {
    border-color: #0F766E;
    background: #EAF7F4;
    color: #0B625C !important;
    transform: translateY(-1px);
}

.profile-social-empty {
    color: #74869A;
    font-size: .88rem;
}

.center-profile-headline {
    color: #0F766E;
    text-transform: uppercase;
    letter-spacing: .105em;
    font-size: clamp(.72rem, 1.7vw, .88rem);
    font-weight: 800;
    line-height: 1.55;
    margin: .3rem auto .7rem;
}

.center-profile-title {
    color: #233548;
    font-size: clamp(1.35rem, 3.2vw, 2.15rem);
    line-height: 1.2;
    letter-spacing: -.03em;
    font-weight: 760;
    max-width: 800px;
    margin: 0 auto .85rem;
}

.center-profile-summary {
    color: #65758B;
    max-width: 790px;
    margin: 0 auto;
    font-size: 1rem;
    line-height: 1.72;
    text-align: center !important;
}

@media (max-width: 700px) {
    .center-hero {
        margin-top: .8rem;
        border-radius: 20px;
        padding: 1.3rem .9rem 1.5rem;
    }

    .center-profile-photo,
    .center-profile-initials {
        width: 145px;
        height: 145px;
    }

    .center-profile-name {
        font-size: clamp(2.25rem, 12vw, 3.3rem);
    }

    .center-profile-socials {
        gap: .42rem;
    }

    .profile-social-link {
        min-height: 2.4rem;
        padding: .53rem .78rem;
        font-size: .84rem;
    }

    .center-profile-summary {
        font-size: .95rem;
        line-height: 1.6;
        text-align: left !important;
    }
}

</style>
""", unsafe_allow_html=True)

# ---------- Navigation ----------
PUBLIC_PAGES = ["Home", "Projects", "Experience", "Skills", "Education", "Contact"]
NAV_LABELS = {
    "Home": content("nav_home", "Home"),
    "Projects": content("nav_projects", "Projects"),
    "Experience": content("nav_experience", "Experience"),
    "Skills": content("nav_skills", "Skills"),
    "Education": content("nav_education", "Education"),
    "Contact": content("nav_contact", "Contact"),
}

if "nav_page" not in st.session_state:
    st.session_state["nav_page"] = "Home"
if "last_public_page" not in st.session_state:
    st.session_state["last_public_page"] = "Home"
if "public_nav" not in st.session_state:
    st.session_state["public_nav"] = st.session_state["last_public_page"]

def _select_public_page():
    selected = st.session_state.get("public_nav", "Home")
    st.session_state["last_public_page"] = selected
    st.session_state["nav_page"] = selected

def _open_admin():
    st.session_state["nav_page"] = "Admin"

nav_left, nav_right = st.columns([7.3, 1.25], gap="medium", vertical_alignment="center")

with nav_left:
    st.radio(
        "Navigation",
        PUBLIC_PAGES,
        horizontal=True,
        format_func=lambda page: NAV_LABELS.get(page, page),
        label_visibility="collapsed",
        key="public_nav",
        on_change=_select_public_page,
    )

with nav_right:
    st.button(
        "Admin",
        key="open_admin_top",
        type="secondary",
        on_click=_open_admin,
        use_container_width=True,
        help="Open the private portfolio administration area"
    )

nav = st.session_state.get("nav_page", "Home")

def render_profile_actions():
    cols = st.columns([1,1,1,3])
    if profile.get("linkedin"):
        with cols[0]:
            st.link_button(content("linkedin_button", "LinkedIn"), profile["linkedin"], use_container_width=True)
    if profile.get("github"):
        with cols[1]:
            st.link_button(content("github_button", "GitHub"), profile["github"], use_container_width=True)
    cv = profile.get("cv_file","")
    if cv and asset_exists(cv):
        with cols[2]:
            cv_data = asset_bytes(cv)
            if cv_data:
                st.download_button(
                    content("download_cv_button", "Download CV"),
                    cv_data,
                    file_name="Bethuel_Sang_CV.pdf",
                    mime="application/pdf",
                    use_container_width=True
                )

def render_project_card(project):
    with st.container(border=False):
        st.markdown('<div class="project-card">', unsafe_allow_html=True)
        cover = project.get("cover_image","")
        if asset_exists(cover):
            st.image(asset_source(cover), use_container_width=True)
        else:
            st.markdown(f'<div class="project-cover">{content("project_empty_image_text", "Add a project screenshot from Admin - Edit Project")}</div>', unsafe_allow_html=True)
        st.markdown(f'<div class="project-cat">{project.get("category","Project")}</div>', unsafe_allow_html=True)
        st.markdown(f'<div class="project-title">{project.get("title","Untitled Project")}</div>', unsafe_allow_html=True)
        st.markdown(f'<div class="project-desc">{project.get("description","")}</div>', unsafe_allow_html=True)
        tools = project.get("tools", [])
        if tools:
            st.markdown("".join([f'<span class="tool-pill">{t}</span>' for t in tools]), unsafe_allow_html=True)

        project_url = live_url(project.get("project_link"))
        code_url = live_url(project.get("github_link"))

        if project_url or code_url:
            b1, b2 = st.columns(2)
            if project_url:
                with b1:
                    st.link_button(
                        content("project_view_button", "View Project"),
                        project_url,
                        use_container_width=True
                    )
            if code_url:
                with b2:
                    st.link_button(
                        content("project_github_button", "View Code"),
                        code_url,
                        use_container_width=True
                    )

        with st.expander(content("project_case_study_label", "Case study")):
            if project.get("challenge"):
                st.markdown(f'**{content("project_challenge_label", "Challenge")}**')
                st.write(project["challenge"])
            if project.get("solution"):
                st.markdown(f'**{content("project_solution_label", "Solution")}**')
                st.write(project["solution"])
            if project.get("impact"):
                st.markdown(f'**{content("project_impact_label", "Impact")}**')
                st.write(project["impact"])
            gallery = project.get("gallery", [])
            existing_gallery = [x for x in gallery if asset_exists(x)]
            if existing_gallery:
                st.markdown(f'**{content("project_screenshots_label", "Screenshots")}**')
                for img in existing_gallery:
                    st.image(asset_source(img), use_container_width=True)
        st.markdown("</div>", unsafe_allow_html=True)

# ---------- Public pages ----------
if nav == "Home":
    profile_name = html.escape(profile.get("name", "Bethuel Sang"))
    profile_headline = html.escape(profile.get("headline", ""))
    profile_title = html.escape(profile.get("hero_title", ""))
    profile_summary = html.escape(profile.get("summary", ""))
    profile_img = profile.get("profile_image", "")
    profile_uri = asset_data_uri(profile_img)

    if profile_uri:
        profile_visual = (
            f'<img class="center-profile-photo" src="{profile_uri}" '
            f'alt="{profile_name} profile picture">'
        )
    else:
        initials = "".join(
            [x[0] for x in profile.get("name", "Bethuel Sang").split()[:2] if x]
        ).upper()
        profile_visual = f'<div class="center-profile-initials">{html.escape(initials)}</div>'

    social_links = []
    for label, key in [
        ("LinkedIn", "linkedin"),
        ("Facebook", "facebook"),
        ("YouTube", "youtube"),
    ]:
        url = str(profile.get(key, "") or "").strip()
        if url:
            safe_url = html.escape(url, quote=True)
            social_links.append(
                f'<a class="profile-social-link" href="{safe_url}" '
                f'target="_blank" rel="noopener noreferrer">{label}</a>'
            )

    social_html = "".join(social_links)
    if not social_html:
        social_html = '<span class="profile-social-empty">Add Facebook and YouTube links from Admin - Profile.</span>'

    st.markdown(
        f"""
        <section class="center-hero">
            <div class="center-profile-visual">{profile_visual}</div>
            <div class="center-profile-name">{profile_name}</div>
            <div class="center-profile-socials">{social_html}</div>
            <div class="center-profile-headline">{profile_headline}</div>
            <div class="center-profile-title">{profile_title}</div>
            <div class="center-profile-summary">{profile_summary}</div>
        </section>
        """,
        unsafe_allow_html=True
    )

    cv = profile.get("cv_file", "")
    if cv and asset_exists(cv):
        cv_left, cv_mid, cv_right = st.columns([2.5, 1.2, 2.5])
        with cv_mid:
            cv_data = asset_bytes(cv)
            if cv_data:
                st.download_button(
                    content("download_cv_button", "Download CV"),
                    cv_data,
                    file_name="Bethuel_Sang_CV.pdf",
                    mime="application/pdf",
                    use_container_width=True,
                    key="home_download_cv"
                )

    auto_current_role = experience[0].get("role", "Trade Development Assistant") if experience else "Trade Development Assistant"
    current_role = content("snapshot_current_role_value", "").strip() or auto_current_role
    published_projects = len([p for p in projects if p.get("status") == "Published"])
    credential_count = len(certifications)

    st.markdown(f"""
    <div class="professional-strip">
        <div class="snapshot-item">
            <div class="snapshot-label">{content("snapshot_current_role_label", "Current role")}</div>
            <div class="snapshot-value">{current_role}</div>
        </div>
        <div class="snapshot-item">
            <div class="snapshot-label">{content("snapshot_core_tools_label", "Core tools")}</div>
            <div class="snapshot-value">{content("snapshot_core_tools_value", "Power BI · Python · SQL · Excel")}</div>
        </div>
        <div class="snapshot-item">
            <div class="snapshot-label">{content("snapshot_portfolio_label", "Portfolio")}</div>
            <div class="snapshot-value">{published_projects} {content("snapshot_projects_suffix", "Projects")}</div>
        </div>
        <div class="snapshot-item">
            <div class="snapshot-label">{content("snapshot_development_label", "Professional development")}</div>
            <div class="snapshot-value">{credential_count} {content("snapshot_certifications_suffix", "Certifications & Training")}</div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    st.markdown(
        f'<div class="section-shell"><div class="eyebrow">{content("home_about_eyebrow", "About me")}</div>'
        f'<div class="section-title">{content("home_about_title", "Where trade insight meets operational clarity.")}</div></div>',
        unsafe_allow_html=True
    )
    st.markdown(f'<div class="section-copy">{profile.get("about","")}</div>', unsafe_allow_html=True)

    featured = [p for p in projects if p.get("featured") and p.get("status") == "Published"]
    if not featured:
        featured = [p for p in projects if p.get("status") == "Published"][:3]

    st.markdown(
        f'<div class="section-shell"><div class="eyebrow">{content("home_featured_eyebrow", "Featured work")}</div>'
        f'<div class="section-title">{content("home_featured_title", "Selected Projects")}</div></div>',
        unsafe_allow_html=True
    )
    for i in range(0, len(featured[:6]), 3):
        cols = st.columns(3, gap="medium")
        for col, project in zip(cols, featured[i:i+3]):
            with col:
                render_project_card(project)

elif nav == "Projects":
    st.markdown(
        f'<div class="section-shell"><div class="eyebrow">{content("projects_eyebrow", "Portfolio")}</div>'
        f'<div class="section-title">{content("projects_title", "Projects")}</div>'
        f'<div class="section-copy">{content("projects_description", "Analytics, automation and trade-development work designed for better decisions.")}</div></div>',
        unsafe_allow_html=True
    )
    published = [p for p in projects if p.get("status") == "Published"]
    cats = ["All"] + sorted(set(p.get("category","Other") for p in published))
    selected = st.selectbox(content("projects_filter_label", "Filter by category"), cats)
    visible = published if selected == "All" else [p for p in published if p.get("category") == selected]
    for i in range(0, len(visible), 3):
        cols = st.columns(3, gap="medium")
        for col, project in zip(cols, visible[i:i+3]):
            with col:
                render_project_card(project)

elif nav == "Experience":
    st.markdown(
        f'<div class="section-shell"><div class="eyebrow">{content("experience_eyebrow", "Career")}</div>'
        f'<div class="section-title">{content("experience_title", "Experience")}</div></div>',
        unsafe_allow_html=True
    )
    for item in experience:
        with st.container(border=True):
            c1, c2 = st.columns([3,1])
            with c1:
                st.subheader(item.get("role",""))
                st.markdown(f"**{item.get('company','')}**")
                st.write(item.get("details",""))
            with c2:
                st.caption(item.get("period",""))

elif nav == "Skills":
    st.markdown(
        f'<div class="section-shell"><div class="eyebrow">{content("skills_eyebrow", "Capabilities")}</div>'
        f'<div class="section-title">{content("skills_title", "A practical toolkit for analytical, commercial and operational work.")}</div></div>',
        unsafe_allow_html=True
    )

    # Skills
    skill_items = list(skills.items())
    for i in range(0, len(skill_items), 3):
        cols = st.columns(3, gap="medium")
        for col, (group, values) in zip(cols, skill_items[i:i+3]):
            with col:
                with st.container(border=True):
                    st.subheader(group)
                    st.write(" · ".join(values))

    # Certifications
    st.markdown(
        f'<div class="section-shell"><div class="eyebrow">{content("certifications_eyebrow", "Professional Development")}</div>'
        f'<div class="section-title">{content("certifications_title", "Selected Certifications & Training")}</div></div>',
        unsafe_allow_html=True
    )

    featured_certs = [c for c in certifications if c.get("featured")]
    other_certs = [c for c in certifications if not c.get("featured")]
    live_credential_count = len([c for c in certifications if live_url(c.get("credential_url"))])
    if live_credential_count:
        st.caption(f"{live_credential_count} certification credential links are available to open.")

    for i in range(0, len(featured_certs), 3):
        cert_cols = st.columns(3, gap="medium")
        for col, cert in zip(cert_cols, featured_certs[i:i+3]):
            with col:
                with st.container(border=True):
                    st.caption(cert.get("issuer", "").upper())
                    st.subheader(cert.get("title", ""))
                    if cert.get("issued"):
                        st.write(cert.get("issued"))
                    if cert.get("credential_id"):
                        st.caption(f"Credential ID: {cert['credential_id']}")
                    if cert.get("skills"):
                        st.write("**Skills:** " + " · ".join(cert["skills"]))
                    credential_url = live_url(cert.get("credential_url"))
                    if credential_url:
                        st.link_button("View credential", credential_url, use_container_width=True)

    if other_certs:
        with st.expander(f'{content("additional_certifications_label", "Additional certifications")} ({len(other_certs)})'):
            for cert in other_certs:
                st.markdown(f"**{cert.get('title','')}** — {cert.get('issuer','')}")
                details = []
                if cert.get("issued"):
                    details.append(cert["issued"])
                if cert.get("credential_id"):
                    details.append(f"Credential ID: {cert['credential_id']}")
                if details:
                    st.caption(" · ".join(details))
                credential_url = live_url(cert.get("credential_url"))
                if credential_url:
                    st.link_button(
                        "View credential",
                        credential_url,
                        key=f"cert-{cert.get('id','')}"
                    )
                st.divider()

elif nav == "Education":
    st.markdown(
        f'<div class="section-shell"><div class="eyebrow">{content("education_eyebrow", "Education")}</div>'
        f'<div class="section-title">{content("education_title", "Building analytical depth with business perspective.")}</div></div>',
        unsafe_allow_html=True
    )
    cols = st.columns(2, gap="medium")
    for col, item in zip(cols, education):
        with col:
            with st.container(border=True):
                st.subheader(item.get("qualification",""))
                st.write(item.get("detail",""))

elif nav == "Contact":
    st.markdown(
        f'<div class="section-shell"><div class="eyebrow">{content("contact_eyebrow", "Contact")}</div>'
        f'<div class="section-title">{content("contact_title", "Let’s turn insight into action.")}</div></div>',
        unsafe_allow_html=True
    )
    st.write(profile.get("availability",""))
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        if profile.get("email"):
            st.markdown(f'**{content("contact_email_label", "Email")}**  \n{profile["email"]}')
    with c2:
        if profile.get("phone"):
            st.markdown(f'**{content("contact_phone_label", "Phone")}**  \n{profile["phone"]}')
    with c3:
        if profile.get("location"):
            st.markdown(f'**{content("contact_location_label", "Location")}**  \n{profile["location"]}')
    with c4:
        if profile.get("linkedin"):
            st.link_button(content("linkedin_button", "LinkedIn"), profile["linkedin"], use_container_width=True)

# ---------- Admin ----------
elif nav == "Admin":
    st.markdown('<div class="section-shell"><div class="eyebrow">Private board</div><div class="section-title">Portfolio Admin</div><div class="section-copy">Manage your complete portfolio here: profile, career information, projects, certifications, CV and cover letters.</div></div>', unsafe_allow_html=True)

    if "admin_authenticated" not in st.session_state:
        st.session_state["admin_authenticated"] = False

    if not st.session_state["admin_authenticated"]:
        with st.form("admin_login_form"):
            password = st.text_input("Admin password", type="password")
            login = st.form_submit_button("Login to Admin", type="primary", use_container_width=True)

        if login:
            if verify_admin_password(password):
                st.session_state["admin_authenticated"] = True
                set_admin_notice("Admin login successful. Welcome back.")
                st.rerun()
            else:
                st.error("Incorrect password.")

        st.caption("Your password can be changed from Admin → Security after login.")
        st.stop()

    logout_col, security_note_col = st.columns([1.1, 5.9], vertical_alignment="center")
    with logout_col:
        if st.button("Log out", use_container_width=True, key="admin_logout"):
            st.session_state["admin_authenticated"] = False
            st.session_state["nav_page"] = st.session_state.get("last_public_page", "Home")
            st.rerun()
    with security_note_col:
        st.caption("Private Admin session is active.")

    show_admin_notice()

    db_ok, db_message = supabase_health()
    if db_ok:
        st.success("Permanent storage is ACTIVE. Direct Supabase REST read/write access is working.")
    else:
        st.error(
            "Permanent storage is NOT active. Admin data can still be lost after a restart. "
            + db_message
        )

    if st.session_state.get("_supabase_write_error"):
        st.error("Last Supabase save error: " + st.session_state["_supabase_write_error"])

    if st.session_state.get("_supabase_read_error"):
        st.warning("Supabase read warning: " + st.session_state["_supabase_read_error"])

    if st.session_state.get("_last_supabase_save"):
        st.caption(
            "Last verified permanent save: "
            + st.session_state["_last_supabase_save"]
        )

    with st.expander("Supabase permanent-storage tools", expanded=not db_ok):
        st.write(db_message)

        if st.button(
            "Run Supabase connection test",
            use_container_width=True,
            key="run_direct_supabase_test"
        ):
            test_ok, test_message = supabase_health()
            if test_ok:
                st.success(test_message)
            else:
                st.error(test_message)

        if db_ok:
            st.caption(
                "Use this once to copy the portfolio currently visible in the app "
                "into Supabase. This is useful if your table is empty or was created "
                "after you had already entered portfolio information."
            )
            if st.button(
                "Sync current portfolio to Supabase",
                use_container_width=True,
                key="sync_all_to_supabase"
            ):
                try:
                    sync_items = [
                        (PROFILE_FILE, profile),
                        (PROJECTS_FILE, projects),
                        (EXPERIENCE_FILE, experience),
                        (SKILLS_FILE, skills),
                        (EDUCATION_FILE, education),
                        (CERTIFICATIONS_FILE, certifications),
                        (SITE_CONTENT_FILE, site_content),
                    ]
                    for sync_path, sync_value in sync_items:
                        write_json(sync_path, sync_value)

                    st.session_state["_last_supabase_save"] = "ALL PORTFOLIO DATA"
                    st.success(
                        "Sync complete. Profile, projects, experience, skills, "
                        "education, certifications and Site Content are now stored "
                        "in Supabase."
                    )
                except Exception as exc:
                    st.error(f"Sync failed: {exc}")
        else:
            st.info(
                "Fix the connection shown above first. The sync button will appear "
                "after the database test succeeds."
            )

    tabs = st.tabs(["Dashboard", "Profile", "Site Content", "Career Data", "Add Project", "Edit Project", "Delete Project", "CV Builder", "Cover Letter", "Security"])

    with tabs[0]:
        st.caption("Your portfolio is preloaded. Use the Admin tabs to add, amend, delete or replace information.")
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Projects", len(projects))
        c2.metric("Published", len([p for p in projects if p.get("status")=="Published"]))
        c3.metric("Featured", len([p for p in projects if p.get("featured")]))
        c4.metric("With screenshots", len([p for p in projects if p.get("cover_image")]))
        st.markdown("### Project Board")
        if projects:
            rows = [{
                "Project": p.get("title",""),
                "Category": p.get("category",""),
                "Status": p.get("status",""),
                "Featured": "Yes" if p.get("featured") else "No",
                "Screenshot": "Yes" if p.get("cover_image") else "No",
                "Project Link": live_url(p.get("project_link")),
                "GitHub / Code": live_url(p.get("github_link")),
            } for p in projects]
            st.dataframe(
                rows,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "Project Link": st.column_config.LinkColumn("Project Link"),
                    "GitHub / Code": st.column_config.LinkColumn("GitHub / Code"),
                }
            )

    with tabs[1]:
        st.markdown("### Profile Settings")
        st.caption("Your current profile is prefilled. Amend any field below and click Save profile.")

        current_image = str(profile.get("profile_image", "") or "").strip()
        if current_image and asset_exists(current_image):
            try:
                preview_left, preview_mid, preview_right = st.columns([2.2, 1, 2.2])
                with preview_mid:
                    st.image(asset_source(current_image), width=180)
                    st.caption("Current profile picture")
            except Exception:
                pass

        with st.form("profile_form"):
            name = st.text_input("Name", profile.get("name",""))
            headline = st.text_input("Professional headline", profile.get("headline",""))
            hero_title = st.text_area("Main headline", profile.get("hero_title",""), height=90)
            summary = st.text_area("Professional summary", profile.get("summary",""), height=130)
            about = st.text_area("About me", profile.get("about",""), height=150)
            location = st.text_input("Location", profile.get("location",""))
            email = st.text_input("Email", profile.get("email",""))
            phone = st.text_input("Phone", profile.get("phone",""))
            linkedin = st.text_input("LinkedIn link", profile.get("linkedin",""))
            facebook = st.text_input("Facebook link", profile.get("facebook",""))
            youtube = st.text_input("YouTube link", profile.get("youtube",""))
            github = st.text_input("GitHub link", profile.get("github",""))
            availability = st.text_area("Contact / availability text", profile.get("availability",""), height=90)

            current_profile_image = str(profile.get("profile_image", "") or "").strip()
            profile_image_url = st.text_input(
                "Profile image URL (optional)",
                value=current_profile_image if current_profile_image.startswith(("http://", "https://")) else "",
                help=(
                    "Use this if the Streamlit file uploader fails. Upload the image to "
                    "Supabase Storage -> portfolio-assets, copy its public URL, and paste it here."
                )
            )

            profile_pic = st.file_uploader(
                "Upload profile picture",
                type=["png","jpg","jpeg","webp"],
                help="PNG, JPG, JPEG or WEBP. If this uploader shows a red !, use the Profile image URL field above."
            )

            cv_upload = st.file_uploader("CV PDF", type=["pdf"])
            save_profile = st.form_submit_button("Save profile", use_container_width=True)

        if save_profile:
            new_profile = dict(profile)
            new_profile.update({
                "name": name.strip(),
                "headline": headline.strip(),
                "hero_title": hero_title.strip(),
                "summary": summary.strip(),
                "about": about.strip(),
                "location": location.strip(),
                "email": email.strip(),
                "phone": phone.strip(),
                "linkedin": linkedin.strip(),
                "facebook": facebook.strip(),
                "youtube": youtube.strip(),
                "github": github.strip(),
                "availability": availability.strip()
            })
            if profile_image_url.strip():
                new_profile["profile_image"] = profile_image_url.strip()

            if profile_pic:
                try:
                    new_profile["profile_image"] = save_uploaded_file(
                        profile_pic,
                        PROFILE_ASSETS,
                        "profile-picture"
                    )
                except Exception as exc:
                    st.error(
                        "The image could not be saved. Use the Profile image URL field as a fallback. "
                        f"Details: {exc}"
                    )

            if cv_upload:
                new_profile["cv_file"] = save_uploaded_file(
                    cv_upload, ASSETS, "Bethuel_Sang_CV"
                )
            write_json(PROFILE_FILE, new_profile)
            set_admin_notice("Profile saved successfully. Your public portfolio has been refreshed.")
            st.rerun()


    with tabs[2]:
        st.markdown("### Site Content")
        st.caption("Your current website wording is prefilled. Amend any field and save. Project and certification counts remain automatic.")

        with st.form("site_content_form"):
            st.markdown("#### Home snapshot")
            sc1, sc2 = st.columns(2)
            with sc1:
                snapshot_current_role_label = st.text_input(
                    "Current role label",
                    content("snapshot_current_role_label", "Current role")
                )
                snapshot_current_role_value = st.text_input(
                    "Current role value",
                    content("snapshot_current_role_value", ""),
                    help="Leave blank to automatically use the first role in Experience."
                )
                snapshot_core_tools_label = st.text_input(
                    "Core tools label",
                    content("snapshot_core_tools_label", "Core tools")
                )
                snapshot_core_tools_value = st.text_input(
                    "Core tools value",
                    content("snapshot_core_tools_value", "Power BI · Python · SQL · Excel")
                )
            with sc2:
                snapshot_portfolio_label = st.text_input(
                    "Portfolio counter label",
                    content("snapshot_portfolio_label", "Portfolio")
                )
                snapshot_projects_suffix = st.text_input(
                    "Projects counter wording",
                    content("snapshot_projects_suffix", "Projects")
                )
                snapshot_development_label = st.text_input(
                    "Professional development counter label",
                    content("snapshot_development_label", "Professional development")
                )
                snapshot_certifications_suffix = st.text_input(
                    "Certifications counter wording",
                    content("snapshot_certifications_suffix", "Certifications & Training")
                )

            st.divider()
            st.markdown("#### Home sections")
            home_about_eyebrow = st.text_input(
                "About section small label",
                content("home_about_eyebrow", "About me")
            )
            home_about_title = st.text_area(
                "About section heading",
                content("home_about_title", "Where trade insight meets operational clarity."),
                height=80
            )
            home_featured_eyebrow = st.text_input(
                "Featured work small label",
                content("home_featured_eyebrow", "Featured work")
            )
            home_featured_title = st.text_input(
                "Featured work heading",
                content("home_featured_title", "Selected Projects")
            )

            st.divider()
            st.markdown("#### Page headings")
            p1, p2 = st.columns(2)
            with p1:
                projects_eyebrow = st.text_input("Projects small label", content("projects_eyebrow", "Portfolio"))
                projects_title = st.text_input("Projects heading", content("projects_title", "Projects"))
                projects_description = st.text_area(
                    "Projects introduction",
                    content("projects_description", "Analytics, automation and trade-development work designed for better decisions."),
                    height=90
                )
                experience_eyebrow = st.text_input("Experience small label", content("experience_eyebrow", "Career"))
                experience_title = st.text_input("Experience heading", content("experience_title", "Experience"))
                skills_eyebrow = st.text_input("Skills small label", content("skills_eyebrow", "Capabilities"))
                skills_title = st.text_area(
                    "Skills heading",
                    content("skills_title", "A practical toolkit for analytical, commercial and operational work."),
                    height=80
                )
            with p2:
                certifications_eyebrow = st.text_input(
                    "Certifications small label",
                    content("certifications_eyebrow", "Professional Development")
                )
                certifications_title = st.text_input(
                    "Certifications heading",
                    content("certifications_title", "Selected Certifications & Training")
                )
                education_eyebrow = st.text_input("Education small label", content("education_eyebrow", "Education"))
                education_title = st.text_area(
                    "Education heading",
                    content("education_title", "Building analytical depth with business perspective."),
                    height=80
                )
                contact_eyebrow = st.text_input("Contact small label", content("contact_eyebrow", "Contact"))
                contact_title = st.text_input(
                    "Contact heading",
                    content("contact_title", "Let’s turn insight into action.")
                )

            st.divider()
            st.markdown("#### Navigation & buttons")
            n1, n2 = st.columns(2)
            with n1:
                nav_home = st.text_input("Navigation: Home", content("nav_home", "Home"))
                nav_projects = st.text_input("Navigation: Projects", content("nav_projects", "Projects"))
                nav_experience = st.text_input("Navigation: Experience", content("nav_experience", "Experience"))
                nav_skills = st.text_input("Navigation: Skills", content("nav_skills", "Skills"))
                nav_education = st.text_input("Navigation: Education", content("nav_education", "Education"))
                nav_contact = st.text_input("Navigation: Contact", content("nav_contact", "Contact"))
            with n2:
                linkedin_button = st.text_input("LinkedIn button", content("linkedin_button", "LinkedIn"))
                github_button = st.text_input("GitHub button", content("github_button", "GitHub"))
                download_cv_button = st.text_input("Download CV button", content("download_cv_button", "Download CV"))
                project_view_button = st.text_input("View Project button", content("project_view_button", "View Project"))
                project_github_button = st.text_input("Project GitHub button", content("project_github_button", "GitHub"))
                projects_filter_label = st.text_input(
                    "Project filter label",
                    content("projects_filter_label", "Filter by category")
                )

            st.divider()
            st.markdown("#### Project case-study wording")
            q1, q2 = st.columns(2)
            with q1:
                project_case_study_label = st.text_input("Case study label", content("project_case_study_label", "Case study"))
                project_challenge_label = st.text_input("Challenge label", content("project_challenge_label", "Challenge"))
                project_solution_label = st.text_input("Solution label", content("project_solution_label", "Solution"))
                project_impact_label = st.text_input("Impact label", content("project_impact_label", "Impact"))
            with q2:
                project_screenshots_label = st.text_input("Screenshots label", content("project_screenshots_label", "Screenshots"))
                additional_certifications_label = st.text_input(
                    "Additional certifications label",
                    content("additional_certifications_label", "Additional certifications")
                )
                contact_email_label = st.text_input("Contact: Email label", content("contact_email_label", "Email"))
                contact_phone_label = st.text_input("Contact: Phone label", content("contact_phone_label", "Phone"))
                contact_location_label = st.text_input("Contact: Location label", content("contact_location_label", "Location"))
                project_empty_image_text = st.text_area(
                    "Project without screenshot message",
                    content("project_empty_image_text", "Add a project screenshot from Admin - Edit Project"),
                    height=75
                )

            save_site_content = st.form_submit_button(
                "Save site content",
                type="primary",
                use_container_width=True
            )

        if save_site_content:
            new_site_content = {
                "nav_home": nav_home.strip(),
                "nav_projects": nav_projects.strip(),
                "nav_experience": nav_experience.strip(),
                "nav_skills": nav_skills.strip(),
                "nav_education": nav_education.strip(),
                "nav_contact": nav_contact.strip(),
                "linkedin_button": linkedin_button.strip(),
                "github_button": github_button.strip(),
                "download_cv_button": download_cv_button.strip(),

                "snapshot_current_role_label": snapshot_current_role_label.strip(),
                "snapshot_current_role_value": snapshot_current_role_value.strip(),
                "snapshot_core_tools_label": snapshot_core_tools_label.strip(),
                "snapshot_core_tools_value": snapshot_core_tools_value.strip(),
                "snapshot_portfolio_label": snapshot_portfolio_label.strip(),
                "snapshot_projects_suffix": snapshot_projects_suffix.strip(),
                "snapshot_development_label": snapshot_development_label.strip(),
                "snapshot_certifications_suffix": snapshot_certifications_suffix.strip(),

                "home_about_eyebrow": home_about_eyebrow.strip(),
                "home_about_title": home_about_title.strip(),
                "home_featured_eyebrow": home_featured_eyebrow.strip(),
                "home_featured_title": home_featured_title.strip(),

                "projects_eyebrow": projects_eyebrow.strip(),
                "projects_title": projects_title.strip(),
                "projects_description": projects_description.strip(),
                "projects_filter_label": projects_filter_label.strip(),
                "experience_eyebrow": experience_eyebrow.strip(),
                "experience_title": experience_title.strip(),
                "skills_eyebrow": skills_eyebrow.strip(),
                "skills_title": skills_title.strip(),
                "certifications_eyebrow": certifications_eyebrow.strip(),
                "certifications_title": certifications_title.strip(),
                "additional_certifications_label": additional_certifications_label.strip(),
                "education_eyebrow": education_eyebrow.strip(),
                "education_title": education_title.strip(),
                "contact_eyebrow": contact_eyebrow.strip(),
                "contact_title": contact_title.strip(),

                "contact_email_label": contact_email_label.strip(),
                "contact_phone_label": contact_phone_label.strip(),
                "contact_location_label": contact_location_label.strip(),

                "project_view_button": project_view_button.strip(),
                "project_github_button": project_github_button.strip(),
                "project_case_study_label": project_case_study_label.strip(),
                "project_challenge_label": project_challenge_label.strip(),
                "project_solution_label": project_solution_label.strip(),
                "project_impact_label": project_impact_label.strip(),
                "project_screenshots_label": project_screenshots_label.strip(),
                "project_empty_image_text": project_empty_image_text.strip()
            }
            write_json(SITE_CONTENT_FILE, new_site_content)
            set_admin_notice("Site content saved successfully. The public website wording has been updated.")
            st.rerun()


    with tabs[3]:
        st.markdown("### Career Data")
        st.caption("Your career data is prefilled. Edit existing rows, add new rows or remove rows. Saved information is used automatically by CV Studio.")

        st.markdown("#### Experience")
        exp_df = pd.DataFrame(experience, columns=["role","company","period","details"])
        exp_edit = st.data_editor(
            exp_df,
            num_rows="dynamic",
            use_container_width=True,
            key="career_experience_editor",
            column_config={
                "role": "Role",
                "company": "Company",
                "period": "Period",
                "details": st.column_config.TextColumn("Details", width="large")
            }
        )
        if st.button("Save experience", use_container_width=True, key="save_experience"):
            clean_exp = exp_edit.fillna("").to_dict("records")
            write_json(EXPERIENCE_FILE, clean_exp)
            set_admin_notice("Experience saved successfully. CV Builder will use the updated information.")
            st.rerun()

        st.divider()
        st.markdown("#### Education")
        edu_df = pd.DataFrame(education, columns=["qualification","detail"])
        edu_edit = st.data_editor(
            edu_df,
            num_rows="dynamic",
            use_container_width=True,
            key="career_education_editor",
            column_config={
                "qualification": "Qualification",
                "detail": st.column_config.TextColumn("Institution / dates / details", width="large")
            }
        )
        if st.button("Save education", use_container_width=True, key="save_education"):
            clean_edu = edu_edit.fillna("").to_dict("records")
            write_json(EDUCATION_FILE, clean_edu)
            set_admin_notice("Education saved successfully.")
            st.rerun()

        st.divider()
        st.markdown("#### Skills")
        skill_rows = [
            {"group": group, "skills": ", ".join(values)}
            for group, values in skills.items()
        ]
        skill_df = pd.DataFrame(skill_rows, columns=["group","skills"])
        skill_edit = st.data_editor(
            skill_df,
            num_rows="dynamic",
            use_container_width=True,
            key="career_skills_editor",
            column_config={
                "group": "Skill Group",
                "skills": st.column_config.TextColumn("Skills (comma separated)", width="large")
            }
        )
        if st.button("Save skills", use_container_width=True, key="save_skills"):
            new_skills = {}
            for row in skill_edit.fillna("").to_dict("records"):
                group = str(row.get("group","")).strip()
                if not group:
                    continue
                new_skills[group] = [x.strip() for x in str(row.get("skills","")).split(",") if x.strip()]
            write_json(SKILLS_FILE, new_skills)
            set_admin_notice("Skills saved successfully. CV Builder will use the updated skills.")
            st.rerun()

        st.divider()
        st.markdown("#### Certifications")
        cert_rows = []
        for c in certifications:
            cert_rows.append({
                "title": c.get("title",""),
                "issuer": c.get("issuer",""),
                "issued": c.get("issued",""),
                "credential_id": c.get("credential_id",""),
                "credential_url": c.get("credential_url",""),
                "skills": ", ".join(c.get("skills",[])),
                "featured": bool(c.get("featured", False))
            })
        cert_df = pd.DataFrame(
            cert_rows,
            columns=["title","issuer","issued","credential_id","credential_url","skills","featured"]
        )
        cert_edit = st.data_editor(
            cert_df,
            num_rows="dynamic",
            use_container_width=True,
            key="career_certifications_editor",
            column_config={
                "title": "Certification",
                "issuer": "Issuer",
                "issued": "Issued",
                "credential_id": "Credential ID",
                "credential_url": st.column_config.LinkColumn("Credential Link"),
                "skills": st.column_config.TextColumn("Skills", width="medium"),
                "featured": st.column_config.CheckboxColumn("Featured")
            }
        )
        if st.button("Save certifications", use_container_width=True, key="save_certifications"):
            new_certs = []
            for idx, row in enumerate(cert_edit.fillna("").to_dict("records")):
                title = str(row.get("title","")).strip()
                if not title:
                    continue
                new_certs.append({
                    "id": slugify(title),
                    "title": title,
                    "issuer": str(row.get("issuer","")).strip(),
                    "issued": str(row.get("issued","")).strip(),
                    "credential_id": str(row.get("credential_id","")).strip(),
                    "credential_url": str(row.get("credential_url","")).strip(),
                    "skills": [x.strip() for x in str(row.get("skills","")).split(",") if x.strip()],
                    "featured": bool(row.get("featured", False))
                })
            write_json(CERTIFICATIONS_FILE, new_certs)
            set_admin_notice("Certifications saved successfully.")
            st.rerun()

    with tabs[4]:
        st.markdown("### Add New Project")
        st.caption("Add a new project without changing your existing project records.")
        with st.form("add_project_form", clear_on_submit=True):
            title = st.text_input("Project title")
            category = st.selectbox("Category", ["Data Analytics","Automation","Business Intelligence","Trade Development","Market Intelligence","Other"])
            status = st.selectbox("Status", ["Published","Draft"])
            featured = st.checkbox("Feature on homepage")
            description = st.text_area("Short description", height=100)
            tools_text = st.text_input("Tools used (comma separated)")
            challenge = st.text_area("Challenge", height=100)
            solution = st.text_area("Solution", height=110)
            impact = st.text_area("Impact / result", height=100)
            project_link = st.text_input("Project / demo link", help="Add a full https:// URL. It will appear as a live View Project button on the public portfolio.")
            github_link = st.text_input("GitHub / code link", help="Add a full https:// URL. It will appear as a live View Code button on the public portfolio.")
            cover = st.file_uploader("Cover screenshot", type=["png","jpg","jpeg","webp"], key="add_cover")
            gallery = st.file_uploader("More screenshots", type=["png","jpg","jpeg","webp"], accept_multiple_files=True, key="add_gallery")
            add_submit = st.form_submit_button("Add project", use_container_width=True)

        if add_submit:
            if not title.strip():
                st.error("Project title is required.")
            else:
                pid = slugify(title)
                cover_path = save_uploaded_file(cover, PROJECT_ASSETS, f"{pid}-cover") if cover else ""
                gallery_paths = [save_uploaded_file(img, PROJECT_ASSETS, f"{pid}-{i+1}") for i, img in enumerate(gallery or [])]
                new_project = {
                    "id": pid,
                    "title": title.strip(),
                    "category": category,
                    "status": status,
                    "featured": featured,
                    "description": description.strip(),
                    "tools": [x.strip() for x in tools_text.split(",") if x.strip()],
                    "challenge": challenge.strip(),
                    "solution": solution.strip(),
                    "impact": impact.strip(),
                    "project_link": project_link.strip(),
                    "github_link": github_link.strip(),
                    "cover_image": cover_path,
                    "gallery": gallery_paths
                }
                projects.append(new_project)
                write_json(PROJECTS_FILE, projects)
                set_admin_notice(f'Project "{title.strip()}" added successfully and published to your portfolio.')
                st.rerun()

    with tabs[5]:
        st.markdown("### Edit Existing Project")
        if not projects:
            st.info("No projects to edit.")
        else:
            labels = {p.get("title","Untitled"): p for p in projects}
            selected_title = st.selectbox("Choose project", list(labels.keys()), key="edit_select")
            p = labels[selected_title]
            with st.form("edit_project_form"):
                title_e = st.text_input("Project title", p.get("title",""))
                category_e = st.selectbox("Category", ["Data Analytics","Automation","Business Intelligence","Trade Development","Market Intelligence","Other"],
                                          index=(["Data Analytics","Automation","Business Intelligence","Trade Development","Market Intelligence","Other"].index(p.get("category")) if p.get("category") in ["Data Analytics","Automation","Business Intelligence","Trade Development","Market Intelligence","Other"] else 5))
                status_e = st.selectbox("Status", ["Published","Draft"], index=0 if p.get("status")=="Published" else 1)
                featured_e = st.checkbox("Feature on homepage", value=bool(p.get("featured")))
                description_e = st.text_area("Short description", p.get("description",""), height=100)
                tools_e = st.text_input("Tools used (comma separated)", ", ".join(p.get("tools",[])))
                challenge_e = st.text_area("Challenge", p.get("challenge",""), height=100)
                solution_e = st.text_area("Solution", p.get("solution",""), height=110)
                impact_e = st.text_area("Impact / result", p.get("impact",""), height=100)
                project_link_e = st.text_input("Project / demo link", p.get("project_link",""), help="Full https:// link to the live project, dashboard or demo.")
                github_link_e = st.text_input("GitHub / code link", p.get("github_link",""), help="Full https:// link to the repository or source code.")
                cover_e = st.file_uploader("Replace cover screenshot", type=["png","jpg","jpeg","webp"], key="edit_cover")
                gallery_e = st.file_uploader("Add more screenshots", type=["png","jpg","jpeg","webp"], accept_multiple_files=True, key="edit_gallery")
                save_edit = st.form_submit_button("Save changes", use_container_width=True)

            if save_edit:
                updated = dict(p)
                updated.update({
                    "title": title_e.strip(),
                    "category": category_e,
                    "status": status_e,
                    "featured": featured_e,
                    "description": description_e.strip(),
                    "tools": [x.strip() for x in tools_e.split(",") if x.strip()],
                    "challenge": challenge_e.strip(),
                    "solution": solution_e.strip(),
                    "impact": impact_e.strip(),
                    "project_link": project_link_e.strip(),
                    "github_link": github_link_e.strip(),
                })
                if cover_e:
                    updated["cover_image"] = save_uploaded_file(cover_e, PROJECT_ASSETS, f"{updated['id']}-cover")
                if gallery_e:
                    existing = updated.get("gallery", [])
                    start = len(existing)
                    existing += [save_uploaded_file(img, PROJECT_ASSETS, f"{updated['id']}-{start+i+1}") for i, img in enumerate(gallery_e)]
                    updated["gallery"] = existing

                new_projects = [updated if x.get("id")==p.get("id") else x for x in projects]
                write_json(PROJECTS_FILE, new_projects)
                set_admin_notice(f'Project "{title_e.strip()}" saved successfully.')
                st.rerun()

    with tabs[6]:
        st.markdown("### Delete Project")
        if not projects:
            st.info("No projects to delete.")
        else:
            delete_title = st.selectbox("Choose project to delete", [p.get("title","Untitled") for p in projects], key="delete_select")
            confirm = st.checkbox("I understand this will remove the project from the portfolio.")
            if st.button("Delete project", type="primary", disabled=not confirm):
                target = next((p for p in projects if p.get("title")==delete_title), None)
                if target:
                    projects = [p for p in projects if p.get("id") != target.get("id")]
                    write_json(PROJECTS_FILE, projects)
                    set_admin_notice(f'Project "{delete_title}" deleted successfully.')
                    st.rerun()



    with tabs[7]:
        st.markdown("### CV Builder")
        st.caption("Tailor the CV to a vacancy, then edit the result before downloading it.")

        j1, j2 = st.columns(2)
        with j1:
            cv_job_title = st.text_input(
                "Target job title",
                value=st.session_state.get("app_job_title", ""),
                key="cv_job_title"
            )
            cv_company = st.text_input(
                "Company",
                value=st.session_state.get("app_company", ""),
                key="cv_company"
            )
        with j2:
            cv_style = st.selectbox("CV style", ["Modern Professional", "Classic ATS"], key="cv_style")
            cv_length = st.selectbox(
                "CV density",
                ["Standard (recommended)", "Compact"],
                key="cv_length"
            )

        cv_content_mode = st.selectbox(
            "CV content",
            [
                "Full career CV (keeps all saved information)",
                "Tailored application CV"
            ],
            index=0,
            help="Full career mode keeps all saved role responsibilities. Tailored mode prioritizes content for the vacancy."
        )
        if cv_content_mode.startswith("Full"):
            st.info("Full Career CV selected: your saved career information will not be automatically removed.")

        cv_job_description = st.text_area(
            "Paste the job description",
            value=st.session_state.get("app_job_description", ""),
            height=250,
            key="cv_job_description",
            placeholder="Paste the duties, requirements and preferred skills here..."
        )

        o1, o2, o3 = st.columns(3)
        with o1:
            cv_include_projects = st.checkbox("Include projects", value=True, key="cv_inc_projects")
        with o2:
            cv_include_certs = st.checkbox("Include certifications", value=True, key="cv_inc_certs")
        with o3:
            cv_bullets = st.slider("Max bullets per role (Tailored mode)", 2, 12, 7, key="cv_bullets")

        if st.button("Create CV draft", type="primary", use_container_width=True, key="create_cv_draft"):
            st.session_state["app_job_title"] = cv_job_title
            st.session_state["app_company"] = cv_company
            st.session_state["app_job_description"] = cv_job_description

            cv_pkg = build_tailored_package(
                profile=profile,
                experience=experience,
                skills=skills,
                education=education,
                projects=projects,
                certifications=certifications,
                job_title=cv_job_title,
                company=cv_company,
                job_description=cv_job_description,
                include_projects=cv_include_projects,
                include_certifications=cv_include_certs,
                max_experience_bullets=cv_bullets,
                preserve_all=cv_content_mode.startswith("Full"),
            )
            st.session_state["cv_package"] = cv_pkg
            st.session_state["cv_summary_edit"] = cv_pkg["summary"]
            st.session_state["cv_skills_edit"] = cv_pkg["skills"]
            st.session_state["cv_selected_exp"] = [
                f"{i}::{x.get('role','')} — {x.get('company','')}"
                for i, x in enumerate(cv_pkg["experience"])
            ]
            st.session_state["cv_selected_projects"] = [x.get("title","") for x in cv_pkg["projects"]]
            st.session_state["cv_selected_certs"] = [x.get("title","") for x in cv_pkg["certifications"]]

        cv_pkg = st.session_state.get("cv_package")
        if cv_pkg:
            if cv_pkg.get("matched_keywords"):
                st.markdown("**Job-description matches found**")
                st.caption(" · ".join(cv_pkg["matched_keywords"][:15]))

            st.markdown("#### 1. Edit your headline & summary")
            edited_target = st.text_input(
                "CV headline",
                value=cv_pkg.get("job_title") or profile.get("headline",""),
                key="cv_headline_edit"
            )
            edited_summary = st.text_area(
                "Professional summary",
                value=st.session_state.get("cv_summary_edit", cv_pkg["summary"]),
                height=150,
                key="cv_summary_text"
            )

            st.markdown("#### 2. Choose skills")
            skill_options = []
            for group, values in skills.items():
                skill_options.extend(values)
            # Keep unique order
            skill_options = list(dict.fromkeys(skill_options))
            default_skill_values = [
                x for x in st.session_state.get("cv_skills_edit", cv_pkg.get("skills", []))
                if x in skill_options
            ]
            selected_skills = st.multiselect(
                "Skills to show",
                options=skill_options,
                default=default_skill_values,
                key="cv_skill_multiselect"
            )
            custom_skills = st.text_input(
                "Additional skills (comma separated, optional)",
                key="cv_custom_skills"
            )

            st.markdown("#### 3. Choose and edit experience")
            exp_options = [
                f"{i}::{x.get('role','')} — {x.get('company','')}"
                for i, x in enumerate(cv_pkg.get("experience", []))
            ]
            selected_exp = st.multiselect(
                "Experience to include",
                options=exp_options,
                default=[x for x in st.session_state.get("cv_selected_exp", exp_options) if x in exp_options],
                key="cv_experience_multiselect"
            )

            exp_edits = {}
            for option in selected_exp:
                idx = int(option.split("::",1)[0])
                item = cv_pkg["experience"][idx]
                st.markdown(f"**{item.get('role','')} — {item.get('company','')}**")
                bullet_text = "\n".join(item.get("bullets", []))
                exp_edits[idx] = st.text_area(
                    "One achievement/responsibility per line",
                    value=bullet_text,
                    height=135,
                    key=f"cv_exp_bullets_{idx}"
                )

            st.markdown("#### 4. Projects & certifications")
            project_options = [p.get("title","") for p in cv_pkg.get("projects", [])]
            selected_projects = st.multiselect(
                "Projects",
                options=project_options,
                default=[x for x in st.session_state.get("cv_selected_projects", project_options) if x in project_options],
                key="cv_project_multiselect"
            )
            cert_options = [c.get("title","") for c in cv_pkg.get("certifications", [])]
            selected_certs = st.multiselect(
                "Certifications",
                options=cert_options,
                default=[x for x in st.session_state.get("cv_selected_certs", cert_options) if x in cert_options],
                key="cv_cert_multiselect"
            )

            if st.button("Build final CV", type="primary", use_container_width=True, key="build_final_cv"):
                final_pkg = dict(cv_pkg)
                final_pkg["job_title"] = edited_target.strip()
                final_pkg["summary"] = edited_summary.strip()

                extra = [x.strip() for x in custom_skills.split(",") if x.strip()]
                final_pkg["skills"] = list(dict.fromkeys(selected_skills + extra))

                final_exp = []
                for option in selected_exp:
                    idx = int(option.split("::",1)[0])
                    item = dict(cv_pkg["experience"][idx])
                    item["bullets"] = [
                        x.strip().lstrip("•- ").strip()
                        for x in exp_edits[idx].splitlines()
                        if x.strip()
                    ]
                    final_exp.append(item)
                final_pkg["experience"] = final_exp
                final_pkg["projects"] = [
                    p for p in cv_pkg.get("projects", []) if p.get("title","") in selected_projects
                ]
                final_pkg["certifications"] = [
                    c for c in cv_pkg.get("certifications", []) if c.get("title","") in selected_certs
                ]

                compact = cv_length == "Compact"
                cv_docx = cv_docx_bytes(final_pkg, style=cv_style, compact=compact)
                cv_pdf = cv_pdf_bytes(final_pkg, compact=compact)

                base = slugify("_".join(
                    x for x in [profile.get("name","Bethuel Sang"), cv_company, cv_job_title] if x
                )).replace("-", "_") or "Bethuel_Sang_CV"

                st.session_state["final_cv"] = {
                    "package": final_pkg,
                    "docx": cv_docx,
                    "pdf": cv_pdf,
                    "base": base,
                }

            final_cv = st.session_state.get("final_cv")
            if final_cv:
                st.success("Final CV is ready.")
                with st.expander("Preview CV content", expanded=False):
                    st.text(cv_plain_text(final_cv["package"]))

                d1, d2 = st.columns(2)
                with d1:
                    st.download_button(
                        "Download CV — Word",
                        final_cv["docx"],
                        file_name=f"{final_cv['base']}_CV.docx",
                        mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                        use_container_width=True
                    )
                with d2:
                    if final_cv.get("pdf"):
                        st.download_button(
                            "Download CV — PDF",
                            final_cv["pdf"],
                            file_name=f"{final_cv['base']}_CV.pdf",
                            mime="application/pdf",
                            use_container_width=True
                        )
                    else:
                        st.warning("PDF export needs ReportLab. Word download is still available.")

    with tabs[8]:
        st.markdown("### Humanized Cover Letter")
        st.caption(
            "Build the letter separately from the CV. Add your reason for wanting the role so the letter sounds like you, "
            "then edit the final draft before downloading."
        )

        c1, c2 = st.columns(2)
        with c1:
            cl_job_title = st.text_input(
                "Target job title",
                value=st.session_state.get("app_job_title", ""),
                key="cl_job_title"
            )
            cl_company = st.text_input(
                "Company",
                value=st.session_state.get("app_company", ""),
                key="cl_company"
            )
            cl_manager = st.text_input("Hiring manager (optional)", key="cl_manager")
        with c2:
            cl_tone = st.selectbox(
                "Writing style",
                ["Natural professional", "Warm & confident", "Concise", "Executive"],
                key="cl_tone"
            )
            cl_length = st.selectbox("Length", ["Standard", "Short"], key="cl_length")

        cl_job_description = st.text_area(
            "Job description",
            value=st.session_state.get("app_job_description", ""),
            height=210,
            key="cl_job_description"
        )
        why_company = st.text_area(
            "Why are you interested in this role/company?",
            height=95,
            placeholder="Example: I like that the role combines market analysis with commercial decision-making...",
            key="cl_why_company"
        )
        personal_note = st.text_area(
            "Personal point you want included (optional)",
            height=85,
            placeholder="Example: I have worked directly with producers, buyers, brokers and regulators...",
            key="cl_personal_note"
        )

        if st.button("Generate humanized draft", type="primary", use_container_width=True, key="generate_cover"):
            st.session_state["app_job_title"] = cl_job_title
            st.session_state["app_company"] = cl_company
            st.session_state["app_job_description"] = cl_job_description

            cl_pkg = build_tailored_package(
                profile=profile,
                experience=experience,
                skills=skills,
                education=education,
                projects=projects,
                certifications=certifications,
                job_title=cl_job_title,
                company=cl_company,
                job_description=cl_job_description,
                include_projects=True,
                include_certifications=False,
                max_experience_bullets=4,
            )
            draft = humanized_cover_letter(
                cl_pkg,
                hiring_manager=cl_manager,
                tone=cl_tone,
                why_company=why_company,
                personal_note=personal_note,
                length=cl_length,
            )
            st.session_state["cover_package"] = cl_pkg
            st.session_state["cover_draft"] = draft

        if st.session_state.get("cover_draft"):
            st.markdown("#### Edit before download")
            final_letter_text = st.text_area(
                "Final cover letter",
                value=st.session_state["cover_draft"],
                height=460,
                key="cover_final_text"
            )

            st.caption(
                "Tip: keep one or two specific examples and your real reason for wanting the role. "
                "That usually sounds more natural than adding more adjectives."
            )

            if st.button("Prepare cover letter downloads", type="primary", use_container_width=True, key="prepare_cover_downloads"):
                cl_docx = cover_letter_docx_from_text(
                    profile, cl_job_title, cl_company, final_letter_text
                )
                cl_pdf = cover_letter_pdf_from_text(
                    profile, cl_job_title, cl_company, final_letter_text
                )
                base = slugify("_".join(
                    x for x in [profile.get("name","Bethuel Sang"), cl_company, cl_job_title] if x
                )).replace("-", "_") or "Bethuel_Sang_Cover_Letter"

                st.session_state["final_cover"] = {
                    "docx": cl_docx,
                    "pdf": cl_pdf,
                    "base": base,
                    "text": final_letter_text
                }

            final_cover = st.session_state.get("final_cover")
            if final_cover:
                st.success("Cover letter is ready.")
                d1, d2 = st.columns(2)
                with d1:
                    st.download_button(
                        "Download Cover Letter — Word",
                        final_cover["docx"],
                        file_name=f"{final_cover['base']}_Cover_Letter.docx",
                        mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                        use_container_width=True
                    )
                with d2:
                    if final_cover.get("pdf"):
                        st.download_button(
                            "Download Cover Letter — PDF",
                            final_cover["pdf"],
                            file_name=f"{final_cover['base']}_Cover_Letter.pdf",
                            mime="application/pdf",
                            use_container_width=True
                        )
                    else:
                        st.warning("PDF export needs ReportLab. Word download is still available.")

                final_cv = st.session_state.get("final_cv")
                if final_cv:
                    files = {
                        f"{final_cv['base']}_CV.docx": final_cv["docx"],
                        f"{final_cv['base']}_CV.pdf": final_cv.get("pdf"),
                        f"{final_cover['base']}_Cover_Letter.docx": final_cover["docx"],
                        f"{final_cover['base']}_Cover_Letter.pdf": final_cover.get("pdf"),
                    }
                    bundle = package_zip(files, "Application_Pack")
                    st.download_button(
                        "Download CV + Cover Letter Pack",
                        bundle,
                        file_name="Bethuel_Sang_Application_Pack.zip",
                        mime="application/zip",
                        type="primary",
                        use_container_width=True
                    )

    with tabs[9]:
        st.markdown("### Security")
        st.write("Change or reset the password used to access your private Admin area.")

        with st.form("change_admin_password_form"):
            current_password = st.text_input("Current password", type="password")
            new_password = st.text_input("New password", type="password")
            confirm_password = st.text_input("Confirm new password", type="password")
            change_password = st.form_submit_button(
                "Reset Admin password",
                type="primary",
                use_container_width=True
            )

        if change_password:
            if not verify_admin_password(current_password):
                st.error("The current password is incorrect.")
            elif len(new_password) < 8:
                st.error("Use at least 8 characters for the new password.")
            elif new_password != confirm_password:
                st.error("The new passwords do not match.")
            elif new_password == current_password:
                st.error("Choose a different password from the current one.")
            else:
                reset_admin_password(new_password)
                set_admin_notice("Admin password changed successfully. Use the new password next time you log in.")
                show_admin_notice()

        st.divider()
        st.markdown("#### Password recovery")
        st.caption(
            "If you ever forget the password on this local computer, close the app, delete "
            "`data/admin_auth.json`, and restart the portfolio. It will restore the initial password "
            "from `.streamlit/secrets.toml`."
        )

st.markdown('<div class="footer">© Bethuel Sang · Trade Development · Data Analytics · Automation</div>', unsafe_allow_html=True)
