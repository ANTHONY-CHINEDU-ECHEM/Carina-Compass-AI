# Data sources

| Source | Endpoint | Access and limits | Licence handling | Stored |
|---|---|---|---|---|
| NICE | NICE Syndication API (base and template configurable) | `NICE_SYNDICATION_API_KEY` required; connector disabled without it | NICE syndication licence | Guideline and appraisal text split at headings |
| NCI PDQ | cancer.gov health professional summaries | robots.txt checked, 0.5 requests per second | US government work, public domain | Sections without reference lists |
| PubMed | NCBI E-utilities `esearch` with history server, `efetch` XML in batches of 200 | 3 requests per second, 10 with `NCBI_API_KEY` | Abstract indexed for retrieval and short quotation | Title, abstract sections, publication types, MeSH, DOI |
| Europe PMC | REST `search` with `cursorMark`, `fullTextXML` | 5 requests per second | Only CC BY and CC0 records kept | JATS sections without references, funding or conflicts |
| ClinicalTrials.gov | API version 2 `/studies` with `pageToken`, page size 1000 | About 50 requests per minute | US government registry | Summary, interventions, eligibility, primary outcomes, structured status, phases, ages, sex, countries, UK sites |
| CIViC | Nightly evidence summary TSV | Single download | CC0 | Accepted predictive, prognostic and diagnostic evidence for lung diseases |
| openFDA | `drug/label.json` by generic name | 240 requests per minute with a key | US public domain | Boxed warning, indications, contraindications, warnings, interactions, specific populations, adverse reactions, mechanism. Dosage sections are never indexed. |
| MedlinePlus | NLM web service `healthTopics` | 1 request per second | US public domain | Plain language summaries, graded lowest |

## The verified seed snapshot

`ingestion/data/seed/` holds 86 records that let the service, tests and evaluation run offline. Each record is a summary written in our own words with a link to the authoritative source and a `verified` note:

* NG122 recommendations grouped by section, checked against the NICE guideline PDF (last updated 8 March 2024, with links to newer appraisals added February 2026).
* 46 NICE technology appraisals with titles and publication dates from the NICE lung cancer listing. A recommendation status is stated only where NG122 or the appraisal title establishes it.
* Eight pivotal trials (FLAURA, ADAURA, KEYNOTE 024, KEYNOTE 189, CheckMate 816, IMpower010, ALINA, CodeBreaK 100) with PMIDs confirmed against PubMed.
* Fifteen ClinicalTrials.gov records with confirmed NCT identifiers and titles; recruitment status is marked as not verified.
* The 8th and 9th edition TNM stage groups and the CG151 and NG234 emergency summaries.
* Two superseded documents (CG121 and TA761) kept to exercise the currency rules.
