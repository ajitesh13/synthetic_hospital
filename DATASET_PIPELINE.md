# Synthetic Hospital Dataset Pipeline

How the released data (`top10_gyn_patients.db`, `benchmark_v1.3.db`) traces back
to the raw (unreleased) source vignettes, per `2609.30027v1.pdf`.

## In plain words

1. **Start**: a made-up patient case (like a med-school exam question) — full text. This text is
   never given out; we never see it.

2. **Two things get pulled out of that text separately:**
   - One AI reads it and picks out the medical facts (what disease, what symptoms) and tags them
     with standard medical codes.
   - A second AI just chops the same text into labeled chunks — "here's the history part," "here's
     the meds part," "here's the labs part" — copying the words as-is, not changing anything.

3. **Several fake cases get stitched into one "patient":** if 3 exam questions describe similar
   diseases in similar-aged people, the system links them together as if they were 3 visits by the
   same person over time. Then:
   - An AI invents a background for that person (job, insurance, allergies, other health issues).
   - An AI decides the order/dates/type of each visit.
   - The chunks from step 2 get copied into each visit, with small fixed edits (add past-visit
     history, add home meds, fill any missing chunk from the invented background).
   - For visits after the first one, an AI rewrites the "story" part (HPI) so it doesn't feel like a
     copy-paste.
   - All the chunks for a visit get glued together into one flowing note — that's what v1 shows you.

4. **Test questions get built from the facts (step 2's AI):** "what's the diagnosis," "summarize the
   chart," etc. — mostly computed automatically from the facts, no AI needed here.
   - One exception: the imaging order (what scan, why). That one's fully AI-written, and it even
     gets told the correct diagnosis first — so it's the most made-up piece of all.

5. **What you get to see, in order of "closest to the original text":**
   - Chunks that were copied as-is → closest to real
   - Chunks that got edited/filled in → a bit changed
   - The glued-together note (v1) → more changed, partly AI-rewritten
   - The diagnosis/summary answers → computed from facts, not text
   - The imaging order → invented by AI knowing the answer already, least "real"

6. **The original exam-question text itself, and the raw chopped chunks (before assigned to a
   patient), are never released** — confirmed in the database's own notes, due to licensing. So the
   closest thing to "raw" you can actually see is the copied-as-is chunks in step 3.

## Technical version

```
raw board-question vignette text (USMLE-style, NOT released)
        │
        ▼
┌─────────────────────────────────────────────────────────┐
│ STAGE 1 — Knowledge ingestion                            │
│ USMLE board questions + fact cards collected, no PHI     │
│ → board_questions (metadata only: subject, topic, ...)   │
└─────────────────────────────────────────────────────────┘
        │
        ├──────────────────────────────┐
        ▼                               ▼
┌─────────────────────────┐   ┌──────────────────────────────┐
│ STAGE 2a — Job A         │   │ STAGE 2b — Job B              │
│ LLM extracts+codes facts │   │ LLM segments vignette into    │
│ → ICD-10-CM/SNOMED/LOINC │   │ 18 EHR section types,         │
│ → ontology graph:        │   │ "copy verbatim, add nothing"  │
│  diagnoses,              │   │ → "source EHR sections"       │
│  clinical_findings,      │   │   (51,940 rows, per-QUESTION, │
│  diagnosis_findings,     │   │   NOT released — excluded     │
│  question_diagnoses,     │   │   per release_info)           │
│  question_findings       │   └──────────────────────────────┘
└─────────────────────────┘               │
        │                                  │
        ▼                                  ▼
┌───────────────────────────────────────────────────────────┐
│ STAGE 3 — Patient clustering + record generation            │
│ Deterministic graph clustering: questions sharing a          │
│ diagnosis + compatible demographics → grouped into patients  │
│ → longitudinal_patients / longitudinal_encounters             │
│                                                                │
│  • Profile LLM call (1/patient) → race, occupation,           │
│    insurance, chronic conditions, meds, etc.                  │
│    → patients.profile  (top10_gyn_patients.db)                │
│                                                                │
│  • Timeline LLM call (1/patient) → orders encounters,         │
│    visit type, department, attending, date                    │
│    → encounters metadata (top10_gyn_patients.db)              │
│                                                                │
│  • Note assembly (deterministic, copies Job B's sections      │
│    from source question → this encounter, + 3 edits:          │
│    PMH prefixed w/ problem list, home meds appended,           │
│    missing sections filled from profile)                      │
│    → encounter_ehr_sections (is_modified flag per row)        │
│    (benchmark_v1.3.db)                                         │
│                                                                │
│  • HPI rewrite LLM call (non-first encounters only)            │
│    → overwrites HPI section text (also is_modified=1)          │
│                                                                │
│  • note_text = deterministic concatenation of all sections     │
│    for that encounter, fixed order, one flat blob               │
│    → encounters.note_text (top10_gyn_patients.db, used in v1)  │
└───────────────────────────────────────────────────────────┘
        │
        ▼
┌───────────────────────────────────────────────────────────┐
│ STAGE 4 — Benchmark construction                             │
│ Mostly deterministic, computed FROM the ontology graph        │
│  • patient_diagnosis, context_summarization,                  │
│    evidence_retrieval labels → deterministic                  │
│    → benchmark_ground_truth, relevance_judgments                │
│  • imaging_indication → EXCEPTION: single LLM call,             │
│    told the confirmed diagnosis, invents order+reference        │
│    → imaging_orders + matching ground_truth rows                 │
│    (most processed/synthetic artifact in the whole set)         │
└───────────────────────────────────────────────────────────┘
        │
        ▼
┌───────────────────────────────────────────────────────────┐
│ STAGE 5 — Domain-faithful simulation                          │
│ FHIR R4 / Epic-style simulated EHR wrapper                     │
│ (not present in our local dbs — not extracted for this set)   │
└───────────────────────────────────────────────────────────┘
        │
        ▼
released db files, as we have them:
  top10_gyn_patients.db   → patients + encounters (profile, note_text) — curated 10-patient extract
  benchmark_v1.3.db       → full benchmark artifacts: sections, ground truth, imaging, ontology, board_questions
```

## Rawness ranking (least → most processed)

1. `encounter_ehr_sections` (`is_modified = 0`) — copy-verbatim from source vignette section
2. `encounter_ehr_sections` (`is_modified = 1`) — deterministically edited/filled during note assembly
3. `note_text` (v1) — deterministic reassembly of #1 + #2; non-first-encounter HPIs are LLM-rewritten on top
4. `benchmark_ground_truth` (patient_diagnosis / summarization / retrieval tasks) — deterministic derivation from the ontology graph
5. `imaging_orders` — fully LLM-authored, conditioned on the answer (confirmed diagnosis) itself — most synthetic

## What's NOT recoverable

Per `benchmark_v1.3.db`'s `release_info.redistributable` field:

> "source text (raw cards, board-question text, fact cards, source EHR sections), licensed terminology
> tables, model outputs and LLM logs are excluded; retrieval judgments are chart sections only"

So the true raw vignette text, and even the stage-2 per-question "source EHR sections" pool, are
deliberately excluded from the release (USMLE licensing). `encounter_ehr_sections` with
`is_modified = 0` is the closest surviving layer — a per-encounter copy assigned to a patient record,
not the original pooled source section itself.

## PDF version history

- `generate_patient_pdfs.py` (v1) → `patient_pdfs/` — flat `note_text` blob per encounter
- `generate_patient_pdfs_v2.py` → `patient_pdfs_v2/` — adds enrichment data
- `generate_patient_pdfs_v3.py` → `patient_pdfs_v3/` — structured EHR sections (with `is_modified` tags)
  instead of flat note_text; ground truth and imaging orders removed as heavily-processed/unrelated
  artifacts (see rawness ranking above)
