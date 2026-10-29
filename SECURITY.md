# Security policy

## Reporting

Report vulnerabilities privately through GitHub security advisories on this repository. Please do not open a public issue for security problems, and never include patient data in a report.

Clinical safety concerns (an unsafe answer, rule or source) are reported with the clinical content issue template, quoting the request id rather than any patient details.

## Design measures

* Identifiers are redacted before retrieval, model calls, caching and logging; the audit log stores a keyed hash of the question only.
* API keys are compared in constant time; admin endpoints need a separate key; requests are rate limited per key.
* Retrieved text is treated as untrusted data and passages that attempt to instruct the model are dropped.
* Containers run as an unprivileged user; the interface sets a restrictive Content Security Policy.
* Ollama deployment keeps all inference inside the organisation's network.

## Supported versions

Only the latest release receives fixes.
