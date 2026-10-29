# Changelog

## 1.0.0 (2026-10-29)

First release.

### Knowledge base
* Connectors for NICE (syndication API), NCI PDQ, PubMed, Europe PMC (CC BY and CC0 only), ClinicalTrials.gov API version 2, CIViC, openFDA (safety sections only) and MedlinePlus.
* Verified seed snapshot of 86 records: NG122 by section, 46 NICE appraisals, eight pivotal trials with confirmed PMIDs, fifteen registry records, TNM 8th and 9th edition, neutropenic sepsis and spinal cord compression guidance.
* Checkpointed harvest, negation aware clinical tagging, SimHash deduplication, supersession graph, section aware chunking, seven step evidence grading.

### Retrieval and generation
* Hybrid dense and BM25 retrieval with reciprocal rank fusion, separate recall and precision queries, synonym expansion and clinical concept tokens.
* Multiplicative clinical priors for evidence grade, recency, UK jurisdiction, biomarker, treatment setting and histology, with conflict penalties and superseded guidance demotion.
* Answerability gate on evidence strength, query coverage and named medicines.
* Claude, OpenAI and Ollama providers behind a router with circuit breakers and an extractive fallback.
* Citation validation, numeric figure checking and claim level faithfulness.

### Clinical tools
* TNM 9th edition staging with 8th edition comparison and T category from tumour size.
* NICE aligned therapy matcher across 56 options.
* Trial matcher over registry records.
* Carboplatin (Calvert), Cockcroft and Gault, BSA and ECOG to Karnofsky mapping.
* Medication safety screen with 27 SmPC referenced rules.
* Oncology emergency triage across eight categories.

### Operations
* FastAPI service with SSE streaming, API keys, rate limits, audit log, feedback and governance summary.
* React clinician interface, standalone browser demo, Docker images, compose stack with Qdrant, Redis, Prometheus, Grafana and Ollama.
* 172 tests, an offline evaluation gate of 48 questions, ruff and mypy in CI.
