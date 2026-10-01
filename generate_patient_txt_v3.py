import json
import sqlite3
from pathlib import Path

PATIENT_DB = "top10_gyn_patients.db"
BENCHMARK_DB = "benchmark_v1.3.db"
OUT_DIR = Path("patient_pdfs_v3")
OUT_DIR.mkdir(exist_ok=True)


def as_list_str(raw):
    try:
        data = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return str(raw) if raw is not None else "None"
    if isinstance(data, list):
        if not data:
            return "None"
        return "\n".join(f"  - {item}" for item in data)
    return str(data)


def profile_text(profile_json):
    try:
        p = json.loads(profile_json)
    except (TypeError, json.JSONDecodeError):
        return str(profile_json)

    lines = []
    simple_keys = [
        ("sex", "Sex"), ("age_at_first_encounter", "Age at First Encounter"),
        ("race_ethnicity", "Race/Ethnicity"), ("insurance", "Insurance"),
        ("occupation", "Occupation"), ("smoking_status", "Smoking Status"),
        ("alcohol_use", "Alcohol Use"),
    ]
    for key, disp in simple_keys:
        if key in p:
            lines.append(f"{disp}: {p[key]}")

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
        lines.append(f"\n{disp}:")
        if key == "home_medications" and isinstance(val, list):
            if val:
                for m in val:
                    lines.append(f"  - {m.get('name','')} - {m.get('dose','')}")
            else:
                lines.append("  None")
        else:
            lines.append(as_list_str(json.dumps(val)))
    return "\n".join(lines)


def build_patient_txt(pconn, bconn, patient_id, out_path):
    cur = pconn.cursor()
    cur.execute("SELECT * FROM patients WHERE patient_id = ?", (patient_id,))
    cols = [d[0] for d in cur.description]
    prow = dict(zip(cols, cur.fetchone()))

    cur.execute(
        "SELECT * FROM encounters WHERE patient_id = ? ORDER BY encounter_date, encounter_order",
        (patient_id,),
    )
    ecols = [d[0] for d in cur.description]
    encounters = [dict(zip(ecols, r)) for r in cur.fetchall()]
    encounter_ids = [e["encounter_id"] for e in encounters]

    bcur = bconn.cursor()

    sections_by_encounter = {}
    if encounter_ids:
        q = ",".join("?" * len(encounter_ids))
        bcur.execute(
            f"""SELECT encounter_id, section_type, section_text, is_modified, section_order
                FROM encounter_ehr_sections WHERE encounter_id IN ({q})
                ORDER BY encounter_id, section_order""",
            encounter_ids,
        )
        for eid, stype, stext, is_mod, sorder in bcur.fetchall():
            sections_by_encounter.setdefault(eid, []).append(
                {"section_type": stype, "section_text": stext,
                 "is_modified": is_mod, "section_order": sorder}
            )

    lines = []
    lines.append(f"PATIENT RECORD — ID {prow['patient_id']}")
    lines.append("=" * 70)
    lines.append(f"Age: {prow['age']}    Sex: {prow['sex']}")
    lines.append(f"Race/Ethnicity: {prow['race_ethnicity']}    Insurance: {prow['insurance']}")
    lines.append(f"Total Encounters: {prow['num_encounters']}    Generation Seed: {prow['generation_seed']}")
    lines.append("")
    lines.append("Primary Diagnoses:")
    lines.append(as_list_str(prow["primary_diagnoses"]))
    lines.append("")
    lines.append("Comorbidities:")
    lines.append(as_list_str(prow["comorbidities"]))
    lines.append("")
    lines.append("-" * 70)
    lines.append("PATIENT PROFILE")
    lines.append("-" * 70)
    lines.append(profile_text(prow["profile"]))
    lines.append("")
    lines.append("=" * 70)
    lines.append(f"ENCOUNTERS ({len(encounters)})")
    lines.append("=" * 70)

    for i, e in enumerate(encounters, start=1):
        eid = e["encounter_id"]
        lines.append("")
        lines.append(f"Encounter {i} — {e['encounter_date']} — {e['department']}")
        lines.append("-" * 70)
        lines.append(f"Encounter ID: {eid}    Type: {e['encounter_type']}")
        lines.append(f"Attending: {e['attending_name']}    Order: {e['encounter_order']}")
        lines.append(f"Department: {e['department']}    Gen. Method: {e['generation_method']}")
        lines.append("")

        secs = sections_by_encounter.get(eid, [])
        if secs:
            lines.append("Structured EHR Sections:")
            for s in secs:
                mod_tag = " (modified)" if s["is_modified"] else ""
                lines.append("")
                lines.append(f"[{s['section_type'].upper()}{mod_tag}]")
                lines.append(s["section_text"] or "")
        else:
            lines.append("Chief Complaint:")
            lines.append(e["chief_complaint"] or "")

    out_path.write_text("\n".join(lines), encoding="utf-8")


def main():
    pconn = sqlite3.connect(PATIENT_DB)
    bconn = sqlite3.connect(BENCHMARK_DB)
    cur = pconn.cursor()
    cur.execute("SELECT patient_id FROM patients ORDER BY CAST(patient_id AS INTEGER)")
    patient_ids = [r[0] for r in cur.fetchall()]

    for pid in patient_ids:
        out_path = OUT_DIR / f"patient_{pid}.txt"
        build_patient_txt(pconn, bconn, pid, out_path)
        print(f"wrote {out_path}")

    pconn.close()
    bconn.close()


if __name__ == "__main__":
    main()
