# Model card

## System

Retrieval augmented generation over a licence tracked thoracic oncology corpus, with deterministic tools for every safety critical figure.

| Component | Production default | Offline default |
|---|---|---|
| Embedder | BAAI bge base en v1.5 (768 dimensions) | Signed feature hashing, 768 dimensions |
| Reranker | BAAI bge reranker base cross encoder | IDF weighted lexical coverage with clinical concept tokens |
| Vector store | Qdrant with payload indexes | In memory NumPy |
| Generator | Claude Sonnet 5.5 through the Anthropic API, prompt cached | Extractive sentence selection |
| Fallbacks | OpenAI, then Ollama or extractive | Extractive |

## Intended users

UK healthcare professionals in lung cancer services. Not for patients.

## Evaluation

The offline gate (`make eval_gate`) runs 48 questions on the seed snapshot. Because the extractive generator copies sentences verbatim, claim support and citation coverage are 1.0 by construction in offline mode; they become informative in `make eval_live`, where the configured model writes the answer.

## Known limitations

* The lexical reranker cannot infer that "exon 19 deletion" is an "EGFR mutation positive" tumour beyond the concept tokens provided; the cross encoder handles this in production.
* The therapy matrix is a curated summary of NICE appraisals and not a formulary.
* Trial eligibility is a registry prefilter only.
* Seed recruitment status is unverified by design.
