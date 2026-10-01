import json
import sqlite3
from pathlib import Path

from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib import colors
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak
)

DB_PATH = "top10_gyn_patients.db"
OUT_DIR = Path("patient_pdfs")
OUT_DIR.mkdir(exist_ok=True)

styles = getSampleStyleSheet()
h1 = ParagraphStyle("h1", parent=styles["Heading1"], spaceAfter=10)
h2 = ParagraphStyle("h2", parent=styles["Heading2"], spaceBefore=14, spaceAfter=6,
                     textColor=colors.HexColor("#1a3c6e"))
h3 = ParagraphStyle("h3", parent=styles["Heading3"], spaceBefore=10, spaceAfter=4)
body = ParagraphStyle("body", parent=styles["BodyText"], leading=14)
mono = ParagraphStyle("mono", parent=styles["BodyText"], fontName="Courier",
                       fontSize=8.5, leading=11)
label = ParagraphStyle("label", parent=styles["BodyText"], fontName="Helvetica-Bold")


def esc(v):
    if v is None:
        return ""
    return str(v).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def as_list_str(raw):
    try:
        data = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return esc(raw)
    if isinstance(data, list):
        if not data:
            return "None"
        return "<br/>".join(f"&bull; {esc(item)}" for item in data)
    return esc(data)


def profile_table(profile_json):
    try:
        p = json.loads(profile_json)
    except (TypeError, json.JSONDecodeError):
        return [Paragraph(esc(profile_json), body)]

    flows = []
    simple_keys = [
        ("sex", "Sex"), ("age_at_first_encounter", "Age at First Encounter"),
        ("race_ethnicity", "Race/Ethnicity"), ("insurance", "Insurance"),
        ("occupation", "Occupation"), ("smoking_status", "Smoking Status"),
        ("alcohol_use", "Alcohol Use"),
    ]
    rows = []
    for key, disp in simple_keys:
        if key in p:
            rows.append([disp, esc(p[key])])
    if rows:
        t = Table(rows, colWidths=[1.8 * inch, 4.5 * inch])
        t.setStyle(TableStyle([
            ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ]))
        flows.append(t)
        flows.append(Spacer(1, 6))

    list_keys = [
        ("allergies", "Allergies"), ("chronic_conditions", "Chronic Conditions"),
        ("home_medications", "Home Medications"),
        ("surgical_history", "Surgical History"),
        ("family_history", "Family History"),
    ]
    for key, disp in list_keys:
        if key not in p:
            continue
        val = p[key]
        flows.append(Paragraph(disp + ":", label))
        if key == "home_medications" and isinstance(val, list):
            if val:
                items = "<br/>".join(
                    f"&bull; {esc(m.get('name',''))} - {esc(m.get('dose',''))}" for m in val
                )
            else:
                items = "None"
            flows.append(Paragraph(items, body))
        else:
            flows.append(Paragraph(as_list_str(json.dumps(val)), body))
        flows.append(Spacer(1, 4))
    return flows


def build_patient_pdf(conn, patient_id, out_path):
    cur = conn.cursor()
    cur.execute("SELECT * FROM patients WHERE patient_id = ?", (patient_id,))
    cols = [d[0] for d in cur.description]
    prow = dict(zip(cols, cur.fetchone()))

    cur.execute(
        "SELECT * FROM encounters WHERE patient_id = ? ORDER BY encounter_date, encounter_order",
        (patient_id,),
    )
    ecols = [d[0] for d in cur.description]
    encounters = [dict(zip(ecols, r)) for r in cur.fetchall()]

    doc = SimpleDocTemplate(
        str(out_path), pagesize=LETTER,
        topMargin=0.6 * inch, bottomMargin=0.6 * inch,
        leftMargin=0.7 * inch, rightMargin=0.7 * inch,
    )
    story = []

    story.append(Paragraph(f"Patient Record — ID {prow['patient_id']}", h1))

    summary_rows = [
        ["Age", esc(prow["age"]), "Sex", esc(prow["sex"])],
        ["Race/Ethnicity", esc(prow["race_ethnicity"]), "Insurance", esc(prow["insurance"])],
        ["Total Encounters", esc(prow["num_encounters"]), "Generation Seed", esc(prow["generation_seed"])],
    ]
    t = Table(summary_rows, colWidths=[1.3 * inch, 2.1 * inch, 1.3 * inch, 2.1 * inch])
    t.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTNAME", (2, 0), (2, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cccccc")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(t)
    story.append(Spacer(1, 10))

    story.append(Paragraph("Primary Diagnoses", h3))
    story.append(Paragraph(as_list_str(prow["primary_diagnoses"]), body))
    story.append(Paragraph("Comorbidities", h3))
    story.append(Paragraph(as_list_str(prow["comorbidities"]), body))

    story.append(Paragraph("Patient Profile", h2))
    story.extend(profile_table(prow["profile"]))

    story.append(Paragraph(f"Encounters ({len(encounters)})", h2))
    for i, e in enumerate(encounters, start=1):
        story.append(Paragraph(
            f"Encounter {i} — {esc(e['encounter_date'])} — {esc(e['department'])}", h3
        ))
        meta_rows = [
            ["Encounter ID", esc(e["encounter_id"]), "Type", esc(e["encounter_type"])],
            ["Attending", esc(e["attending_name"]), "Order", esc(e["encounter_order"])],
            ["Department", esc(e["department"]), "Gen. Method", esc(e["generation_method"])],
        ]
        mt = Table(meta_rows, colWidths=[1.2 * inch, 2.3 * inch, 1.1 * inch, 2.2 * inch])
        mt.setStyle(TableStyle([
            ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
            ("FONTNAME", (2, 0), (2, -1), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 8.5),
            ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#dddddd")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ]))
        story.append(mt)
        story.append(Spacer(1, 4))
        story.append(Paragraph("Chief Complaint:", label))
        story.append(Paragraph(esc(e["chief_complaint"]), body))
        story.append(Spacer(1, 4))
        story.append(Paragraph("Full Note:", label))
        note_html = esc(e["note_text"]).replace("\n", "<br/>")
        story.append(Paragraph(note_html, mono))
        if i < len(encounters):
            story.append(PageBreak())

    doc.build(story)


def main():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT patient_id FROM patients ORDER BY CAST(patient_id AS INTEGER)")
    patient_ids = [r[0] for r in cur.fetchall()]

    for pid in patient_ids:
        out_path = OUT_DIR / f"patient_{pid}.pdf"
        build_patient_pdf(conn, pid, out_path)
        print(f"wrote {out_path}")

    conn.close()


if __name__ == "__main__":
    main()
