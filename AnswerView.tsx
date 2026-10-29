import { Fragment } from "react";
import type { FinalResult, Source } from "../types";

const CITATION = /\[(\d{1,2})\]/g;

function renderLine(line: string, sources: Source[], onCite: (id: number) => void) {
  const parts: (string | JSX.Element)[] = [];
  let last = 0;
  for (const match of line.matchAll(CITATION)) {
    const index = match.index ?? 0;
    parts.push(line.slice(last, index));
    const id = Number(match[1]);
    const source = sources.find((s) => s.id === id);
    parts.push(
      <button key={`${index}-${id}`} className="cite" title={source?.title ?? `Source ${id}`} onClick={() => onCite(id)}>
        {id}
      </button>,
    );
    last = index + match[0].length;
  }
  parts.push(line.slice(last));
  return parts;
}

interface Props {
  text: string;
  sources: Source[];
  final: FinalResult | null;
  streaming: boolean;
  onCite: (id: number) => void;
}

export default function AnswerView({ text, sources, final, streaming, onCite }: Props) {
  if (!text && !final) return null;
  const body = final ? final.answer : text;
  const paragraphs = body.split(/\n{2,}/);
  return (
    <section className={`answer status-${final?.status ?? "streaming"}`} aria-live="polite">
      {paragraphs.map((p, i) => {
        const judgement = p.startsWith("Clinical judgement:");
        const figure = p.startsWith("Figure check:");
        return (
          <p key={i} className={judgement ? "judgement" : figure ? "figure-check" : undefined}>
            {p.split("\n").map((line, j) => (
              <Fragment key={j}>
                {j > 0 ? <br /> : null}
                {renderLine(line, sources, onCite)}
              </Fragment>
            ))}
          </p>
        );
      })}
      {streaming ? <span className="cursor" aria-hidden /> : null}
      {final && final.status === "answered" ? (
        <footer className="answer-meta">
          <span className={final.grounded ? "badge status-ok" : "badge status-check"}>{final.grounded ? "Grounded" : "Check grounding"}</span>
          {final.citation_report ? <span>Citation coverage {Math.round(final.citation_report.coverage * 100)}%</span> : null}
          {final.faithfulness ? <span>Claim support {Math.round(final.faithfulness.claim_support * 100)}%</span> : null}
          <span>{final.provider}{final.model ? ` · ${final.model}` : ""}</span>
          {final.fallbacks_used.length ? <span>Fallbacks: {final.fallbacks_used.join(", ")}</span> : null}
          <span>{final.latency_ms} ms{final.cached ? " · cached" : ""}</span>
        </footer>
      ) : null}
    </section>
  );
}
