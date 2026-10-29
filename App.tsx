import { useEffect, useRef, useState } from "react";
import { askStream, health } from "./api";
import AnswerView from "./components/AnswerView";
import EmergencyBanner from "./components/EmergencyBanner";
import EvidenceTray from "./components/EvidenceTray";
import Feedback from "./components/Feedback";
import PatientContextPanel from "./components/PatientContextPanel";
import ToolCards from "./components/ToolCards";
import type { Emergency, FinalResult, PatientContext, Provider, Source, ToolCard } from "./types";

const EMPTY_CONTEXT: PatientContext = { biomarkers: [], prior_treatments: [], current_medicines: [], conditions: [], allergies: [] };

const EXAMPLES = [
  "First line options for stage IVA lung adenocarcinoma with EGFR exon 19 deletion, PS 1?",
  "KRAS G12C NSCLC that progressed after chemo-immunotherapy: options and trials?",
  "cT2a N2b M0 adenocarcinoma: what stage is this in the 9th edition?",
  "Day 10 after carboplatin and pemetrexed, temperature 38.6 with rigors",
];

export default function App() {
  const [question, setQuestion] = useState("");
  const [context, setContext] = useState<PatientContext>(EMPTY_CONTEXT);
  const [provider, setProvider] = useState<Provider | "">("");
  const [emergencies, setEmergencies] = useState<Emergency[]>([]);
  const [tools, setTools] = useState<ToolCard[]>([]);
  const [sources, setSources] = useState<Source[]>([]);
  const [text, setText] = useState("");
  const [final, setFinal] = useState<FinalResult | null>(null);
  const [redactions, setRedactions] = useState<Record<string, number>>({});
  const [streaming, setStreaming] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [highlighted, setHighlighted] = useState<number | null>(null);
  const [inScope, setInScope] = useState(false);
  const [indexInfo, setIndexInfo] = useState<string>("");
  const abort = useRef<AbortController | null>(null);

  useEffect(() => {
    health().then((h) => h && setIndexInfo(`${h.index.documents.toLocaleString("en-GB")} documents · ${h.index.chunks.toLocaleString("en-GB")} passages`));
  }, []);

  const submit = async (q: string) => {
    if (!q.trim() || streaming) return;
    abort.current?.abort();
    const controller = new AbortController();
    abort.current = controller;
    setEmergencies([]);
    setTools([]);
    setSources([]);
    setText("");
    setFinal(null);
    setError(null);
    setRedactions({});
    setStreaming(true);
    try {
      await askStream(q, context, provider || undefined, inScope, {
        onMeta: (m) => setRedactions(m.redactions),
        onEmergency: setEmergencies,
        onTools: setTools,
        onSources: setSources,
        onToken: (t) => setText((prev) => prev + t),
        onFinal: (f) => {
          setFinal(f);
          if (f.sources.length) setSources(f.sources);
          setInScope(f.status !== "out_of_scope");
        },
        onError: setError,
      }, controller.signal);
    } catch (e) {
      if ((e as Error).name !== "AbortError") setError("The service could not be reached.");
    } finally {
      setStreaming(false);
    }
  };

  const cite = (id: number) => {
    setHighlighted(id);
    document.getElementById(`source-${id}`)?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  };

  return (
    <div className="shell">
      <header className="topbar">
        <div className="brand">
          <svg viewBox="0 0 32 32" width="28" height="28" aria-hidden>
            <circle cx="16" cy="16" r="14" fill="none" stroke="currentColor" strokeWidth="1.5" />
            <path d="M16 5 L16 15 M16 15 L8 25 M16 15 L24 25" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
            <circle cx="16" cy="15" r="2.2" fill="currentColor" />
          </svg>
          <div>
            <h1>Carina Compass</h1>
            <p>Evidence grounded lung cancer treatment support</p>
          </div>
        </div>
        <div className="topbar-meta">
          {indexInfo ? <span className="muted">{indexInfo}</span> : null}
          <select aria-label="Model provider" value={provider} onChange={(e) => setProvider(e.target.value as Provider | "")}>
            <option value="">Default model</option>
            <option value="anthropic">Claude</option>
            <option value="openai">OpenAI</option>
            <option value="ollama">Local (Ollama)</option>
            <option value="extractive">Extractive only</option>
          </select>
        </div>
      </header>

      <main className="layout">
        <PatientContextPanel value={context} onChange={setContext} />

        <section className="consult" aria-label="Consultation">
          <form
            className="ask"
            onSubmit={(e) => {
              e.preventDefault();
              submit(question);
            }}
          >
            <textarea
              value={question}
              placeholder="Ask about staging, treatment options, evidence, trials or dosing checks"
              onChange={(e) => setQuestion(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) submit(question);
              }}
              rows={3}
            />
            <div className="ask-actions">
              <div className="examples">
                {EXAMPLES.map((ex) => (
                  <button type="button" key={ex} className="example" onClick={() => { setQuestion(ex); submit(ex); }}>
                    {ex}
                  </button>
                ))}
              </div>
              <button className="primary" type="submit" disabled={streaming || !question.trim()}>
                {streaming ? "Answering" : "Ask"}
              </button>
            </div>
          </form>

          {Object.keys(redactions).length ? (
            <p className="redacted">Redacted before processing: {Object.entries(redactions).map(([k, v]) => `${k.toLowerCase().replaceAll("_", " ")} ×${v}`).join(", ")}</p>
          ) : null}
          {error ? <p className="error">{error}</p> : null}

          <EmergencyBanner alerts={emergencies} />
          <ToolCards cards={tools} />
          <AnswerView text={text} sources={sources} final={final} streaming={streaming} onCite={cite} />
          {final && final.status === "answered" ? <Feedback requestId={final.request_id} /> : null}

          <p className="legal">
            Decision support for registered healthcare professionals. Not a medical device. Confirm against the full NICE guidance, the SmPC and local SACT protocols, and discuss at the lung cancer MDT.
          </p>
        </section>

        <EvidenceTray sources={sources} highlighted={highlighted} />
      </main>
    </div>
  );
}
