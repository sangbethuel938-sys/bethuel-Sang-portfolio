
from io import BytesIO
from datetime import date
import re
import zipfile

from docx import Document
from docx.shared import Inches, Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

try:
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak
    REPORTLAB_AVAILABLE = True
except Exception:
    REPORTLAB_AVAILABLE = False


STOPWORDS = {
    "the","and","for","with","that","this","from","your","you","our","are","will","have","has",
    "job","role","work","working","team","teams","company","business","experience","skills","skill",
    "ability","required","requirements","preferred","candidate","responsibilities","responsibility",
    "including","into","across","using","use","support","strong","good","excellent","within","about",
    "their","they","who","what","when","where","how","not","but","can","may","must","should","would",
    "years","year","position","professional","management","manage","related","other","key"
}

KNOWN_PHRASES = [
    "power bi","power query","data analysis","data analytics","business intelligence",
    "business analysis","market intelligence","trade development","stakeholder management",
    "stakeholder engagement","risk management","project management","process improvement",
    "data visualization","data cleaning","data transformation","dashboard development",
    "microsoft excel","excel","python","sql","postgresql","pandas","numpy","streamlit",
    "forecasting","demand planning","inventory management","supply chain",
    "commercial analytics","reporting","automation","customer service",
    "account management","quality management","internal audit","cybersecurity"
]


def clean_text(text):
    if text is None:
        return ""
    return (str(text)
            .replace("\u00a0", " ")
            .replace("–", "-")
            .replace("—", "-")
            .replace("’", "'")
            .replace("“", '"')
            .replace("”", '"')
            .strip())


def tokenize(text):
    words = re.findall(r"[A-Za-z][A-Za-z0-9+#.\-]{1,}", clean_text(text).lower())
    return [w.strip(".-") for w in words if len(w) > 2 and w not in STOPWORDS]


def job_signals(job_title="", job_description=""):
    text = f"{job_title} {job_description}".lower()
    counts = {}
    for token in tokenize(text):
        counts[token] = counts.get(token, 0) + 1
    keywords = [k for k, _ in sorted(counts.items(), key=lambda x: (-x[1], x[0]))]
    phrases = {p for p in KNOWN_PHRASES if p in text}
    return keywords, phrases


def score_text(text, keywords, phrases):
    lower = clean_text(text).lower()
    toks = set(tokenize(lower))
    score = 0
    for idx, kw in enumerate(keywords[:80]):
        if kw in toks:
            score += max(1, 8 - min(idx // 10, 6))
    for phrase in phrases:
        if phrase in lower:
            score += 12
    return score


def split_bullets(details):
    text = clean_text(details)
    if not text:
        return []
    parts = re.split(r"\s*;\s*|\.\s+(?=[A-Z0-9])", text)
    bullets = []
    for part in parts:
        part = part.strip(" .;-")
        if part:
            bullets.append(part)
    return bullets


def all_skills(skills):
    rows = []
    for group, values in (skills or {}).items():
        for value in values:
            rows.append((group, value))
    return rows


def rank_skills(skills, job_title="", job_description=""):
    values = all_skills(skills)
    if not (job_title.strip() or job_description.strip()):
        return [x[1] for x in values]
    keywords, phrases = job_signals(job_title, job_description)
    scored = []
    for i, (group, skill) in enumerate(values):
        scored.append((score_text(f"{group} {skill}", keywords, phrases), -i, skill))
    scored.sort(reverse=True)
    return [x[2] for x in scored]


def rank_items(items, job_title="", job_description="", fields=None):
    fields = fields or []
    if not (job_title.strip() or job_description.strip()):
        return list(items)
    keywords, phrases = job_signals(job_title, job_description)
    scored = []
    for i, item in enumerate(items):
        text = " ".join(clean_text(item.get(f, "")) for f in fields)
        text += " " + " ".join(item.get("tools", []) or [])
        text += " " + " ".join(item.get("skills", []) or [])
        scored.append((score_text(text, keywords, phrases), -i, item))
    scored.sort(reverse=True)
    return [x[2] for x in scored]


def rank_experience(experience, job_title="", job_description="", bullet_limit=5):
    keywords, phrases = job_signals(job_title, job_description)
    result = []
    for idx, item in enumerate(experience or []):
        bullets = split_bullets(item.get("details", ""))
        if job_title.strip() or job_description.strip():
            scored = [(score_text(b, keywords, phrases), -i, b) for i, b in enumerate(bullets)]
            scored.sort(reverse=True)
            bullets = [x[2] for x in scored[:bullet_limit]]
        else:
            bullets = bullets[:bullet_limit]
        copy = dict(item)
        copy["bullets"] = bullets
        copy["_score"] = score_text(
            " ".join([item.get("role",""), item.get("company",""), item.get("details","")]),
            keywords, phrases
        )
        copy["_index"] = idx
        result.append(copy)
    # Keep chronology but put current role first; don't scramble career history.
    return result


def tailored_summary(profile, skills, job_title="", company="", job_description=""):
    top = rank_skills(skills, job_title, job_description)[:6]
    role = job_title.strip()
    intro = "Business and data analytics professional"
    if role:
        intro += f" targeting {role} opportunities"
    middle = (
        " with experience across trade development, market intelligence, business reporting, "
        "operational analysis and process improvement."
    )
    skill_line = ""
    if top:
        skill_line = f" Brings hands-on capability in {', '.join(top[:5])}."
    close = (
        " Experienced in turning operational and market data into clear reporting, practical dashboards "
        "and business improvements while working with cross-functional stakeholders."
    )
    return intro + middle + skill_line + close


def build_tailored_package(profile, experience, skills, education, projects, certifications,
                           job_title="", company="", job_description="",
                           include_projects=True, include_certifications=True,
                           max_experience_bullets=5, preserve_all=False):
    ranked_projects = rank_items(
        [p for p in projects or [] if p.get("status", "Published") == "Published"],
        job_title, job_description,
        fields=["title","category","description","challenge","solution","impact"]
    )
    ranked_certs = rank_items(
        certifications or [],
        job_title, job_description,
        fields=["title","issuer","issued"]
    )
    ranked_skill_values = rank_skills(skills, job_title, job_description)
    # Full Career mode keeps every saved responsibility instead of shortening roles.
    experience_rows = rank_experience(
        experience,
        job_title if not preserve_all else "",
        job_description if not preserve_all else "",
        bullet_limit=(999 if preserve_all else max_experience_bullets)
    )

    keywords, phrases = job_signals(job_title, job_description)
    corpus = " ".join(
        ranked_skill_values
        + [profile.get("summary","")]
        + [x.get("details","") for x in experience or []]
        + [x.get("description","") for x in projects or []]
        + [x.get("title","") for x in certifications or []]
    ).lower()
    corpus_tokens = set(tokenize(corpus))
    matched = []
    for p in sorted(phrases):
        if p in corpus:
            matched.append(p)
    for kw in keywords:
        if kw in corpus_tokens and kw not in matched:
            matched.append(kw)
        if len(matched) >= 16:
            break

    return {
        "profile": dict(profile or {}),
        "job_title": clean_text(job_title),
        "company": clean_text(company),
        "job_description": clean_text(job_description),
        "summary": (
            clean_text(profile.get("summary",""))
            if preserve_all
            else tailored_summary(profile, skills, job_title, company, job_description)
        ),
        "skills": ranked_skill_values if preserve_all else ranked_skill_values[:16],
        "experience": experience_rows,
        "education": list(education or []),
        "projects": (
            [p for p in projects or [] if p.get("status", "Published") == "Published"]
            if (include_projects and preserve_all)
            else (ranked_projects[:4] if include_projects else [])
        ),
        "certifications": (
            list(certifications or [])
            if (include_certifications and preserve_all)
            else (ranked_certs[:7] if include_certifications else [])
        ),
        "matched_keywords": matched,
    }


def cv_plain_text(package):
    p = package
    profile = p["profile"]
    lines = [
        profile.get("name",""),
        p.get("job_title") or profile.get("headline",""),
        " | ".join([x for x in [
            profile.get("location",""), profile.get("email",""),
            profile.get("phone",""), profile.get("linkedin","")
        ] if x]),
        "",
        "PROFESSIONAL SUMMARY",
        p.get("summary",""),
        "",
        "CORE SKILLS",
        " | ".join(p.get("skills",[])),
        "",
        "PROFESSIONAL EXPERIENCE",
    ]
    for item in p.get("experience", []):
        lines += [
            f"{item.get('role','')} | {item.get('company','')} | {item.get('period','')}"
        ]
        for b in item.get("bullets", []):
            lines.append(f"- {b}")
        lines.append("")
    if p.get("projects"):
        lines.append("SELECTED PROJECTS")
        for item in p["projects"]:
            tools = ", ".join(item.get("tools",[]))
            lines.append(f"{item.get('title','')}" + (f" | {tools}" if tools else ""))
            if item.get("impact") or item.get("description"):
                lines.append(f"- {item.get('impact') or item.get('description')}")
        lines.append("")
    lines.append("EDUCATION")
    for item in p.get("education", []):
        lines.append(f"{item.get('qualification','')} | {item.get('detail','')}")
    if p.get("certifications"):
        lines += ["", "SELECTED CERTIFICATIONS"]
        for item in p["certifications"]:
            lines.append(f"{item.get('title','')} | {item.get('issuer','')} | {item.get('issued','')}")
    return "\n".join(lines).strip()


def set_cell_margins(cell, top=60, start=70, bottom=60, end=70):
    tc = cell._tc
    tcPr = tc.get_or_add_tcPr()
    tcMar = tcPr.first_child_found_in("w:tcMar")
    if tcMar is None:
        tcMar = OxmlElement("w:tcMar")
        tcPr.append(tcMar)
    for m, v in [("top",top),("start",start),("bottom",bottom),("end",end)]:
        node = tcMar.find(qn(f"w:{m}"))
        if node is None:
            node = OxmlElement(f"w:{m}")
            tcMar.append(node)
        node.set(qn("w:w"), str(v))
        node.set(qn("w:type"), "dxa")



def _doc_style(doc, compact=False):
    sec = doc.sections[0]
    sec.top_margin = Inches(0.42 if not compact else 0.34)
    sec.bottom_margin = Inches(0.42 if not compact else 0.34)
    sec.left_margin = Inches(0.55)
    sec.right_margin = Inches(0.55)

    normal = doc.styles["Normal"]
    normal.font.name = "Aptos"
    normal.font.size = Pt(9.0 if not compact else 8.5)
    normal.font.color.rgb = RGBColor(35, 53, 72)
    normal.paragraph_format.space_after = Pt(2.2)
    normal.paragraph_format.line_spacing = 1.02


def _add_bottom_rule(paragraph, color="0F766E", size="7"):
    pPr = paragraph._p.get_or_add_pPr()
    pBdr = OxmlElement("w:pBdr")
    bottom = OxmlElement("w:bottom")
    bottom.set(qn("w:val"), "single")
    bottom.set(qn("w:sz"), size)
    bottom.set(qn("w:space"), "1")
    bottom.set(qn("w:color"), color)
    pBdr.append(bottom)
    pPr.append(pBdr)


def _section(doc, text, color=(16,42,67)):
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(6)
    p.paragraph_format.space_after = Pt(3)

    r = p.add_run(text.upper())
    r.bold = True
    r.font.name = "Aptos"
    r.font.size = Pt(10.2)
    r.font.color.rgb = RGBColor(*color)

    _add_bottom_rule(p)
    return p


def _bullet(doc, text):
    p = doc.add_paragraph()
    p.paragraph_format.left_indent = Inches(0.18)
    p.paragraph_format.first_line_indent = Inches(-0.12)
    p.paragraph_format.space_after = Pt(1.6)
    p.paragraph_format.line_spacing = 1.02

    marker = p.add_run("• ")
    marker.bold = True
    marker.font.color.rgb = RGBColor(15, 118, 110)

    run = p.add_run(clean_text(text))
    run.font.name = "Aptos"
    run.font.size = Pt(8.9)
    run.font.color.rgb = RGBColor(35, 53, 72)
    return p


def _role_row(doc, item):
    table = doc.add_table(rows=1, cols=2)
    table.autofit = False
    left, right = table.rows[0].cells
    set_cell_margins(left, top=20, start=0, bottom=10, end=0)
    set_cell_margins(right, top=20, start=0, bottom=10, end=0)

    p1 = left.paragraphs[0]
    p1.paragraph_format.space_after = Pt(0)
    r = p1.add_run(clean_text(item.get("role","")))
    r.bold = True
    r.font.name = "Aptos"
    r.font.size = Pt(10)
    r.font.color.rgb = RGBColor(16,42,67)

    p1.add_run("\n")
    c = p1.add_run(clean_text(item.get("company","")))
    c.italic = True
    c.font.name = "Aptos"
    c.font.size = Pt(8.6)
    c.font.color.rgb = RGBColor(90,106,123)

    p2 = right.paragraphs[0]
    p2.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    p2.paragraph_format.space_after = Pt(0)
    rr = p2.add_run(clean_text(item.get("period","")))
    rr.font.name = "Aptos"
    rr.font.size = Pt(8.0)
    rr.font.color.rgb = RGBColor(90,106,123)
    return table


def cv_docx_bytes(package, style="Modern Professional", compact=False):
    d = Document()
    _doc_style(d, compact=compact)
    profile = package["profile"]

    # Clean, left-aligned professional header.
    p = d.add_paragraph()
    p.paragraph_format.space_after = Pt(1)
    r = p.add_run(clean_text(profile.get("name","")).upper())
    r.bold = True
    r.font.name = "Aptos Display"
    r.font.size = Pt(23 if not compact else 21)
    r.font.color.rgb = RGBColor(16,42,67)

    target = package.get("job_title") or profile.get("headline","")
    p = d.add_paragraph()
    p.paragraph_format.space_after = Pt(3)
    r = p.add_run(clean_text(target).upper())
    r.bold = True
    r.font.name = "Aptos"
    r.font.size = Pt(9.4)
    r.font.color.rgb = RGBColor(15,118,110)

    contact = "  |  ".join([x for x in [
        profile.get("location",""),
        profile.get("phone",""),
        profile.get("email",""),
        profile.get("linkedin","")
    ] if x])
    p = d.add_paragraph()
    p.paragraph_format.space_after = Pt(4)
    rr = p.add_run(clean_text(contact))
    rr.font.name = "Aptos"
    rr.font.size = Pt(8.2)
    rr.font.color.rgb = RGBColor(90,106,123)
    _add_bottom_rule(p, size="9")

    _section(d, "Professional Profile")
    p = d.add_paragraph(clean_text(package.get("summary","")))
    p.paragraph_format.line_spacing = 1.04
    p.paragraph_format.space_after = Pt(3)

    _section(d, "Core Expertise")
    p = d.add_paragraph(" • ".join(clean_text(x) for x in package.get("skills",[])))
    p.paragraph_format.line_spacing = 1.06

    _section(d, "Professional Experience")
    experience = package.get("experience", [])
    for idx, item in enumerate(experience):
        _role_row(d, item)
        for b in item.get("bullets", []):
            _bullet(d, b)

    if package.get("projects"):
        _section(d, "Selected Projects")
        for item in package["projects"]:
            p = d.add_paragraph()
            p.paragraph_format.space_after = Pt(1)

            r = p.add_run(clean_text(item.get("title","")))
            r.bold = True
            r.font.size = Pt(9.2)
            r.font.color.rgb = RGBColor(16,42,67)

            tools = ", ".join(item.get("tools",[]))
            if tools:
                t = p.add_run("  |  " + clean_text(tools))
                t.italic = True
                t.font.size = Pt(8.1)
                t.font.color.rgb = RGBColor(90,106,123)

            desc = item.get("impact") or item.get("description")
            if desc:
                _bullet(d, desc)

    _section(d, "Education")
    for item in package.get("education", []):
        p = d.add_paragraph()
        p.paragraph_format.space_after = Pt(2)

        r = p.add_run(clean_text(item.get("qualification","")))
        r.bold = True
        r.font.size = Pt(9.1)
        r.font.color.rgb = RGBColor(16,42,67)

        p.add_run("\n")
        rr = p.add_run(clean_text(item.get("detail","")))
        rr.font.size = Pt(8.3)
        rr.font.color.rgb = RGBColor(90,106,123)

    if package.get("certifications"):
        _section(d, "Selected Certifications")
        cert_text = " • ".join(
            " - ".join(x for x in [
                clean_text(item.get("title","")),
                clean_text(item.get("issuer",""))
            ] if x)
            for item in package["certifications"]
        )
        p = d.add_paragraph(cert_text)
        p.paragraph_format.line_spacing = 1.05

    bio = BytesIO()
    d.save(bio)
    return bio.getvalue()


def _pdf_styles(compact=False):
    if not REPORTLAB_AVAILABLE:
        return None

    s = getSampleStyleSheet()
    body_size = 8.4 if not compact else 8.0

    return {
        "name": ParagraphStyle(
            "Name", parent=s["Heading1"], fontName="Helvetica-Bold",
            fontSize=20, leading=21, textColor=colors.HexColor("#102A43"),
            spaceAfter=1
        ),
        "target": ParagraphStyle(
            "Target", parent=s["Normal"], fontName="Helvetica-Bold",
            fontSize=9.2, leading=11, textColor=colors.HexColor("#0F766E"),
            spaceAfter=2
        ),
        "contact": ParagraphStyle(
            "Contact", parent=s["Normal"], fontName="Helvetica",
            fontSize=7.6, leading=9.5, textColor=colors.HexColor("#5A6A7B"),
            spaceAfter=5
        ),
        "heading": ParagraphStyle(
            "Heading", parent=s["Heading2"], fontName="Helvetica-Bold",
            fontSize=10.1, leading=11.5, textColor=colors.HexColor("#102A43"),
            spaceBefore=5, spaceAfter=2.5,
            borderWidth=0, borderPadding=0
        ),
        "body": ParagraphStyle(
            "Body", parent=s["BodyText"], fontName="Helvetica",
            fontSize=body_size, leading=10.7, textColor=colors.HexColor("#233548"),
            spaceAfter=2.5
        ),
        "small": ParagraphStyle(
            "Small", parent=s["BodyText"], fontName="Helvetica",
            fontSize=7.5, leading=9, textColor=colors.HexColor("#5A6A7B"),
            spaceAfter=1
        ),
        "role": ParagraphStyle(
            "Role", parent=s["BodyText"], fontName="Helvetica-Bold",
            fontSize=9.2, leading=10.4, textColor=colors.HexColor("#102A43"),
            spaceAfter=0
        ),
        "bullet": ParagraphStyle(
            "Bullet", parent=s["BodyText"], fontName="Helvetica",
            fontSize=8.15 if not compact else 7.85, leading=10.1,
            leftIndent=9, firstLineIndent=-6,
            textColor=colors.HexColor("#233548"), spaceAfter=1.2
        ),
        "project": ParagraphStyle(
            "Project", parent=s["BodyText"], fontName="Helvetica-Bold",
            fontSize=8.7, leading=10, textColor=colors.HexColor("#102A43"),
            spaceAfter=1
        ),
    }


def _pdf_rule(story):
    rule = Table([[""]], colWidths=[180*mm], rowHeights=[0.7*mm])
    rule.setStyle(TableStyle([
        ("BACKGROUND",(0,0),(-1,-1),colors.HexColor("#0F766E")),
        ("LEFTPADDING",(0,0),(-1,-1),0),
        ("RIGHTPADDING",(0,0),(-1,-1),0),
        ("TOPPADDING",(0,0),(-1,-1),0),
        ("BOTTOMPADDING",(0,0),(-1,-1),0),
    ]))
    story.append(rule)
    story.append(Spacer(1, 2))


def cv_pdf_bytes(package, compact=False):
    if not REPORTLAB_AVAILABLE:
        return None

    bio = BytesIO()
    doc = SimpleDocTemplate(
        bio, pagesize=A4,
        rightMargin=12*mm, leftMargin=12*mm,
        topMargin=(9 if compact else 10)*mm,
        bottomMargin=(9 if compact else 10)*mm,
        title=f"{package['profile'].get('name','')} CV"
    )
    S = _pdf_styles(compact)
    story = []
    profile = package["profile"]

    story.append(Paragraph(clean_text(profile.get("name","")).upper(), S["name"]))
    story.append(Paragraph(
        clean_text(package.get("job_title") or profile.get("headline","")).upper(),
        S["target"]
    ))

    contact = " | ".join([x for x in [
        profile.get("location",""),
        profile.get("phone",""),
        profile.get("email",""),
        profile.get("linkedin","")
    ] if x])
    story.append(Paragraph(clean_text(contact), S["contact"]))
    _pdf_rule(story)

    story.append(Paragraph("PROFESSIONAL PROFILE", S["heading"]))
    _pdf_rule(story)
    story.append(Paragraph(clean_text(package.get("summary","")), S["body"]))

    story.append(Paragraph("CORE EXPERTISE", S["heading"]))
    _pdf_rule(story)
    story.append(Paragraph(clean_text(" • ".join(package.get("skills",[]))), S["body"]))

    story.append(Paragraph("PROFESSIONAL EXPERIENCE", S["heading"]))
    _pdf_rule(story)

    experience = package.get("experience", [])
    for idx, item in enumerate(experience):
        table = Table(
            [[Paragraph(clean_text(item.get("role","")), S["role"]),
              Paragraph(clean_text(item.get("period","")), S["small"])]],
            colWidths=[135*mm, 45*mm]
        )
        table.setStyle(TableStyle([
            ("VALIGN",(0,0),(-1,-1),"TOP"),
            ("ALIGN",(1,0),(1,0),"RIGHT"),
            ("LEFTPADDING",(0,0),(-1,-1),0),
            ("RIGHTPADDING",(0,0),(-1,-1),0),
            ("TOPPADDING",(0,0),(-1,-1),0),
            ("BOTTOMPADDING",(0,0),(-1,-1),0),
        ]))
        story.append(table)
        story.append(Paragraph(clean_text(item.get("company","")), S["small"]))

        for b in item.get("bullets", []):
            story.append(Paragraph("• " + clean_text(b), S["bullet"]))
        story.append(Spacer(1, 2))

    if package.get("projects"):
        story.append(Paragraph("SELECTED PROJECTS", S["heading"]))
        _pdf_rule(story)
        for item in package["projects"]:
            tools = ", ".join(item.get("tools",[]))
            title = clean_text(item.get("title",""))
            if tools:
                title += "  |  " + clean_text(tools)
            story.append(Paragraph(title, S["project"]))
            desc = item.get("impact") or item.get("description")
            if desc:
                story.append(Paragraph("• " + clean_text(desc), S["bullet"]))

    story.append(Paragraph("EDUCATION", S["heading"]))
    _pdf_rule(story)
    for item in package.get("education", []):
        story.append(Paragraph(
            f"<b>{clean_text(item.get('qualification',''))}</b><br/>{clean_text(item.get('detail',''))}",
            S["body"]
        ))

    if package.get("certifications"):
        story.append(Paragraph("SELECTED CERTIFICATIONS", S["heading"]))
        _pdf_rule(story)
        cert_text = " • ".join(
            " - ".join(x for x in [
                clean_text(item.get("title","")),
                clean_text(item.get("issuer",""))
            ] if x)
            for item in package["certifications"]
        )
        story.append(Paragraph(cert_text, S["body"]))

    doc.build(story)
    return bio.getvalue()


def humanized_cover_letter(package, hiring_manager="", tone="Natural professional",
                           why_company="", personal_note="", length="Standard"):
    profile = package["profile"]
    job = package.get("job_title") or "this opportunity"
    company = package.get("company") or "your organization"
    skills = package.get("skills", [])[:5]
    current = package.get("experience", [{}])[0] if package.get("experience") else {}
    project = package.get("projects", [{}])[0] if package.get("projects") else {}

    greeting = f"Dear {clean_text(hiring_manager)}," if clean_text(hiring_manager) else "Dear Hiring Manager,"

    if clean_text(why_company):
        opening = (
            f"The {job} opportunity at {company} stood out to me because {clean_text(why_company).rstrip('.')}."
        )
    else:
        opening = (
            f"The {job} opportunity at {company} closely matches the direction of my work in data, "
            f"commercial insight and process improvement."
        )

    current_para = ""
    if current:
        current_para = (
            f"In my current role as {current.get('role','')} at {current.get('company','')}, "
            f"I analyse operational and market information, turn it into practical reporting, and work with "
            f"different stakeholders to improve decisions and day-to-day processes."
        )

    evidence = ""
    if project.get("title"):
        tools = ", ".join(project.get("tools", [])[:3])
        evidence = (
            f"One example is my {project.get('title')} work"
            + (f", where I used {tools}" if tools else "")
            + f" to {clean_text(project.get('impact') or project.get('description','')).rstrip('.').lower()}."
        )

    fit = ""
    if skills:
        fit = (
            f"For this role, the capabilities I would bring most directly are {', '.join(skills[:-1])}"
            + (f" and {skills[-1]}" if len(skills) > 1 else skills[0])
            + "."
        )

    personal = ""
    if clean_text(personal_note):
        personal = clean_text(personal_note)
        if not personal.endswith((".", "!", "?")):
            personal += "."

    if tone == "Warm & confident":
        close = (
            f"I would value the chance to bring this practical, curious approach to {company} and to learn from the team "
            f"while contributing from the outset. I would be glad to discuss the role further."
        )
    elif tone == "Executive":
        close = (
            f"I would welcome a conversation about how my combination of analytics, commercial awareness and operational "
            f"execution can support {company}'s priorities."
        )
    elif tone == "Concise":
        close = (
            f"I would welcome the opportunity to discuss how this experience could support {company}."
        )
    else:
        close = (
            f"I would welcome the opportunity to discuss how my experience can contribute to {company}, particularly where "
            f"clear analysis, stakeholder coordination and practical execution need to come together."
        )

    paragraphs = [greeting, opening, current_para, evidence, fit, personal, close, "Kind regards,", profile.get("name","")]
    paragraphs = [p for p in paragraphs if clean_text(p)]

    if length == "Short":
        keep = [paragraphs[0], paragraphs[1]]
        if current_para:
            keep.append(current_para)
        if evidence:
            keep.append(evidence)
        if personal:
            keep.append(personal)
        keep += [close, "Kind regards,", profile.get("name","")]
        paragraphs = keep

    return "\n\n".join(paragraphs)


def cover_letter_docx_from_text(profile, job_title, company, text):
    d = Document()
    _doc_style(d)
    p = d.add_paragraph()
    r = p.add_run(clean_text(profile.get("name","")))
    r.bold = True
    r.font.size = Pt(17)
    r.font.color.rgb = RGBColor(16,42,67)

    contact = " | ".join([x for x in [
        profile.get("location",""), profile.get("email",""),
        profile.get("phone",""), profile.get("linkedin","")
    ] if x])
    p = d.add_paragraph(clean_text(contact))
    if p.runs:
        p.runs[0].font.size = Pt(8.4)
        p.runs[0].font.color.rgb = RGBColor(80,97,118)

    d.add_paragraph(date.today().strftime("%d %B %Y"))
    if company:
        d.add_paragraph(clean_text(company))
    if job_title:
        p = d.add_paragraph()
        rr = p.add_run(f"RE: APPLICATION FOR {clean_text(job_title).upper()}")
        rr.bold = True

    for para in [x.strip() for x in clean_text(text).split("\n\n") if x.strip()]:
        p = d.add_paragraph(para)
        p.paragraph_format.space_after = Pt(7)

    bio = BytesIO()
    d.save(bio)
    return bio.getvalue()


def cover_letter_pdf_from_text(profile, job_title, company, text):
    if not REPORTLAB_AVAILABLE:
        return None
    bio = BytesIO()
    doc = SimpleDocTemplate(
        bio, pagesize=A4, rightMargin=20*mm, leftMargin=20*mm,
        topMargin=18*mm, bottomMargin=18*mm,
        title=f"{profile.get('name','')} Cover Letter"
    )
    S = _pdf_styles(False)
    story = [
        Paragraph(clean_text(profile.get("name","")), S["name"]),
        Paragraph(clean_text(" | ".join([x for x in [
            profile.get("location",""), profile.get("email",""),
            profile.get("phone",""), profile.get("linkedin","")
        ] if x])), S["contact"]),
        Spacer(1, 6),
        Paragraph(date.today().strftime("%d %B %Y"), S["body"])
    ]
    if company:
        story.append(Paragraph(clean_text(company), S["body"]))
    if job_title:
        story.append(Paragraph(f"<b>RE: APPLICATION FOR {clean_text(job_title).upper()}</b>", S["body"]))
    story.append(Spacer(1, 5))
    for para in [x.strip() for x in clean_text(text).split("\n\n") if x.strip()]:
        story.append(Paragraph(clean_text(para), S["body"]))
        story.append(Spacer(1, 4))
    doc.build(story)
    return bio.getvalue()


def package_zip(files, base_name="Application_Pack"):
    bio = BytesIO()
    with zipfile.ZipFile(bio, "w", zipfile.ZIP_DEFLATED) as z:
        for filename, payload in files.items():
            if payload:
                z.writestr(filename, payload)
    return bio.getvalue()
