import type { Source } from "../types";

const SOURCE_LABEL: Record<string, string> = {
  nice_guideline: "NICE guideline",
  nice_appraisal: "NICE appraisal",
  nci_pdq: "NCI PDQ",
  pubmed: "PubMed",
  europe_pmc: "Europe PMC",
  clinical_trial: "Trial registry",
  civic: "CIViC",
  drug_label: "Drug label",
  patient_info: "Patient information",
  staging_reference: "Staging reference",
};

interface Props {
  sources: Source[];
  highlighted: number | null;
}

export default function EvidenceTray({ sources, highlighted }: Props) {
  return (
    <aside className="panel evidence" aria-label="Evidence">
      <header className="panel-head">
        <h2>Evidence</h2>
        <p className="hint">Ranked UK guidance first, then trials, then registries.</p>
      </header>
      {!sources.length ? <p className="muted">Sources appear here as soon as retrieval finishes.</p> : null}
      <ol className="sources">
        {sources.map((s) => (
          <li key={s.chunk_id} id={`source-${s.id}`} className={highlighted === s.id ? "source active" : "source"}>
            <div className="source-head">
              <span className="source-id">{s.id}</span>
              <a href={s.url} target="_blank" rel="noreferrer">{s.title}</a>
            </div>
            <div className="source-tags">
              <span className="tag">{SOURCE_LABEL[s.source] ?? s.source}</span>
              <span className={`tag grade grade-${s.evidence_grade}`} title={s.evidence_label}>Grade {s.evidence_grade}</span>
              {s.year ? <span className="tag">{s.year}</span> : null}
              <span className="tag">{s.jurisdiction}</span>
              {s.superseded_by ? <span className="tag superseded">Replaced by {s.superseded_by}</span> : null}
            </div>
            {s.section ? <div className="muted">{s.section}</div> : null}
            <p className="excerpt">{s.excerpt}</p>
          </li>
        ))}
      </ol>
    </aside>
  );
}
