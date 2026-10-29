import type { DoseStep, SafetyFlag, TherapyOption, ToolCard, TrialMatch } from "../types";

const STATUS_CLASS: Record<string, string> = {
  recommended: "status-ok",
  recommended_cdf: "status-cdf",
  see_appraisal: "status-check",
  not_recommended: "status-no",
  terminated: "status-no",
};

function Staging({ result }: { result: Record<string, unknown> }) {
  const notes = (result.notes as string[]) ?? [];
  return (
    <div className="stage">
      <div className="stage-group">
        <span className="stage-label">Stage</span>
        <strong>{String(result.stage_group)}</strong>
        <span className="mono">{`${result.t} ${result.n} ${result.m}`}</span>
      </div>
      {result.eighth_edition_stage_group ? <p className="muted">8th edition: {String(result.eighth_edition_stage_group)}</p> : null}
      <p>{String(result.resectability_hint)}</p>
      {notes.map((n) => (
        <p key={n} className="note">{n}</p>
      ))}
    </div>
  );
}

function Therapy({ result }: { result: Record<string, unknown> }) {
  const options = (result.options as TherapyOption[]) ?? [];
  const missing = (result.missing_information as string[]) ?? [];
  return (
    <div>
      <table className="options">
        <thead>
          <tr>
            <th>Regimen</th>
            <th>NICE</th>
            <th>Status</th>
          </tr>
        </thead>
        <tbody>
          {options.map((o) => (
            <tr key={o.option_id}>
              <td>
                {o.regimen}
                {o.evidence_trial ? (
                  <span className="muted">
                    {" "}
                    · {o.evidence_url ? <a href={o.evidence_url} target="_blank" rel="noreferrer">{o.evidence_trial}</a> : o.evidence_trial}
                  </span>
                ) : null}
                {o.caveats.map((c) => (
                  <div key={c} className="note">{c}</div>
                ))}
              </td>
              <td className="mono">{o.nice_url ? <a href={o.nice_url} target="_blank" rel="noreferrer">{o.nice_reference}</a> : o.nice_reference}</td>
              <td>
                <span className={`badge ${STATUS_CLASS[o.nice_status] ?? ""}`}>{o.nice_status_label}</span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {missing.length ? <p className="note">Missing for a firmer match: {missing.join("; ")}.</p> : null}
      <p className="disclaimer">{String(result.disclaimer ?? "")}</p>
    </div>
  );
}

function Trials({ result }: { result: Record<string, unknown> }) {
  const matches = (result.matches as TrialMatch[]) ?? [];
  if (!matches.length) return <p className="muted">No registry records matched the profile.</p>;
  return (
    <ul className="trials">
      {matches.map((t) => (
        <li key={t.nct_id}>
          <a href={t.url} target="_blank" rel="noreferrer" className="mono">{t.nct_id}</a> {t.title}
          <div className="muted">
            {t.phases.join(", ") || "Phase not stated"} · {t.status_verified ? t.status.toLowerCase().replaceAll("_", " ") : "status not verified"}
          </div>
          {t.cautions.map((c) => (
            <div key={c} className="note">{c}</div>
          ))}
        </li>
      ))}
    </ul>
  );
}

function Dose({ steps }: { steps: DoseStep[] }) {
  return (
    <div>
      {steps.map((s) => (
        <div key={s.calculation} className="dose">
          <div className="dose-head">
            <span>{s.calculation}</span>
            <strong>
              {s.value} {s.unit}
            </strong>
          </div>
          {s.working.map((w) => (
            <div key={w} className="mono muted">{w}</div>
          ))}
          {s.warnings.map((w) => (
            <div key={w} className="note">{w}</div>
          ))}
        </div>
      ))}
      <p className="disclaimer">Calculation check only. Confirm against the local SACT protocol and pharmacist verification.</p>
    </div>
  );
}

function Safety({ result }: { result: Record<string, unknown> }) {
  const flags = (result.flags as SafetyFlag[]) ?? [];
  if (!flags.length) return <p className="muted">No flags from the curated rules. This does not replace a pharmacist review.</p>;
  return (
    <ul className="flags">
      {flags.map((f) => (
        <li key={`${f.rule_id}-${f.planned}`} className={`flag sev-${f.severity}`}>
          <span className="badge">{f.severity}</span> <strong>{f.planned}</strong> with {f.trigger}
          <div>{f.message}</div>
          <div className="muted">{f.source}</div>
        </li>
      ))}
    </ul>
  );
}

export default function ToolCards({ cards }: { cards: ToolCard[] }) {
  if (!cards.length) return null;
  return (
    <section className="tools" aria-label="Deterministic clinical tools">
      {cards.map((card) => (
        <article key={card.tool} className={`tool tool-${card.status}`}>
          <header>
            <h3>{card.title}</h3>
            <span className="verified">Verified tool</span>
          </header>
          {card.status === "needs_input" ? <p className="note">Needs: {card.missing.join(", ")}</p> : null}
          {card.status === "error" ? <p className="note">{card.message}</p> : null}
          {card.status === "ok" && card.result && card.tool === "staging" ? <Staging result={card.result} /> : null}
          {card.result && card.tool === "therapy_options" ? <Therapy result={card.result} /> : null}
          {card.status === "ok" && card.result && card.tool === "trial_matching" ? <Trials result={card.result} /> : null}
          {card.status === "ok" && card.result && card.tool === "carboplatin_calvert" ? <Dose steps={card.result.steps as DoseStep[]} /> : null}
          {card.status === "ok" && card.result && card.tool === "bsa" ? <Dose steps={[card.result as unknown as DoseStep]} /> : null}
          {card.status === "ok" && card.result && card.tool === "safety_screen" ? <Safety result={card.result} /> : null}
        </article>
      ))}
    </section>
  );
}
