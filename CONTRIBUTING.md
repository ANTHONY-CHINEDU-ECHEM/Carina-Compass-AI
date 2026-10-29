# Contributing

Thank you for helping improve Carina Compass AI. Because the system supports clinical decisions, contributions follow a few extra rules.

## Development

```bash
cp .env.example .env
make install
make seed
make check
```

`make check` runs ruff, mypy, the test suite, the evaluation gate and the README style check, exactly as CI does.

## Clinical content

* Clinical rules live only in `backend/carina/knowledge/*.yaml`. Never hard code a dose, threshold or recommendation in Python.
* Every change to a rule file needs a named clinical reviewer in the pull request, an updated `last_reviewed` date and a check of `docs/clinical_safety_case.md`.
* Seed records must be written in your own words, link to the authoritative source and say in `verified` how they were checked. Do not add a statement you could not confirm; write "check the appraisal" instead.
* Add golden set questions to `evaluation/golden_set.jsonl` for any behaviour that changes answers.

## Privacy

Never commit patient data, real or invented identifiers, harvested corpora or audit logs. The `data/` directory is ignored by git for this reason.

## Style

Python 3.11 or newer, formatted with ruff, typed for mypy. British English in user facing text. The README avoids hyphens and dashes in prose; `scripts/check_readme.py` enforces this.
