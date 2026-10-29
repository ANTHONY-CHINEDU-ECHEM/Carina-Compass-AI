# Clinical safety case (DCB0129 draft)

This is the manufacturer's draft clinical safety case for Carina Compass AI, structured for the NHS standard DCB0129 (Clinical Risk Management: its Application in the Manufacture of Health IT Systems). A deploying organisation completes DCB0160 for its own use and must appoint a Clinical Safety Officer before any use in patient care.

## Intended use

Carina Compass AI is decision support for registered healthcare professionals in UK lung cancer services: thoracic and medical oncologists, clinical oncologists, respiratory physicians, thoracic surgeons, lung cancer clinical nurse specialists and oncology pharmacists. It retrieves and summarises published guidance and evidence, runs deterministic calculations and rule checks, and cites every claim. It does not diagnose, does not prescribe, and is not a medical device. Final decisions remain with the treating clinician and the lung cancer multidisciplinary team.

Out of scope: use by patients or the public, use without clinical oversight, use as a prescribing system, and use outside UK practice without reconfiguring the jurisdiction rules.

## Hazard log

| ID | Hazard | Cause | Effect | Controls | Residual risk |
|---|---|---|---|---|---|
| H1 | Wrong or invented dose presented | Language model generates a figure | Overdose or underdose | Doses never come from the model: carboplatin, BSA and creatinine clearance come from deterministic formulae with plausibility limits; every clinical figure in an answer must appear in a cited source or it is flagged inline; US label dosage sections are never indexed | Low |
| H2 | Treatment shown as NHS funded when it is not | Outdated or wrong appraisal status | Inappropriate treatment expectation | Therapy matrix lists the governing NICE TA and its status, with "check the appraisal" where status was not confirmed; review date surfaced in every tool card | Low |
| H3 | Withdrawn guidance presented as current | Superseded edition retrieved | Outdated care | Supersession graph halves the ranking score, labels the source and instructs the model; answer sentence carries "replaced by" note | Low |
| H4 | Adjuvant evidence applied to metastatic disease, or one driver's evidence to another | Retrieval mismatch | Inappropriate regimen | Chunk level setting and biomarker tags with match boosts and conflict penalties; sentence level filters in the extractive generator; therapy matcher filters by setting and biomarker | Low |
| H5 | Emergency delayed | Retrieval or model latency | Harm from neutropenic sepsis, cord compression, airway compromise | Triage runs before retrieval and streams first; never cached; never blocked by the evidence gate | Low |
| H6 | Patient identifiers leave the organisation | Clinician pastes identifiable text | Data protection breach | Redaction before retrieval, model calls, cache and logs; NHS numbers validated with modulus 11; audit stores only a keyed hash; Ollama option keeps all inference on site | Low |
| H7 | Answer beyond the evidence | Thin or irrelevant retrieval | Unsupported recommendation | Answerability gate on evidence strength, query coverage and presence of named medicines and biomarkers; explicit abstention | Medium (depends on corpus completeness) |
| H8 | Prompt injection through a harvested document | Malicious or malformed source text | Model follows embedded instructions | Injection filter drops such passages; sources are marked as untrusted data in the system prompt | Low |
| H9 | Trial shown as open when closed | Stale registry snapshot | Futile referral | Status verified flag; seed records carry "status not verified" caution; `make ingest_trials` refreshes | Low |
| H10 | Interaction missed | Curated rules incomplete | Adverse drug event | Screen states its scope and directs to the BNF and pharmacist review; unknown medicines are listed back to the user | Medium |
| H11 | Model vendor outage during MDT | Provider failure | Delay | Ordered fallback chain with circuit breakers, ending in the extractive generator that needs no network | Low |

## Rule file governance

Every clinical rule lives in a YAML file under `backend/carina/knowledge/` with a version, a `last_reviewed` date and a `review_status`. The `/v1/knowledge` endpoint lists them so the safety officer can see what is in force. Changes require clinical review in the pull request template, a bump of `last_reviewed`, and a check of this hazard log.

## Monitoring after deployment

Prometheus alerts fire on any unsupported figure, falling claim support, abstention spikes, provider fallbacks and dropped injection passages. The governance summary at `/v1/audit/summary` reports grounded rate, abstentions, emergencies, superseded sources cited and clinician feedback, including answers rated unsafe.
