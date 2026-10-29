import type { Emergency, FinalResult, PatientContext, Provider, Source, ToolCard } from "./types";

const API_KEY = (import.meta.env.VITE_API_KEY as string | undefined) ?? "";

function headers(): HeadersInit {
  const base: Record<string, string> = { "Content-Type": "application/json" };
  if (API_KEY) base["X-API-Key"] = API_KEY;
  return base;
}

export interface StreamHandlers {
  onMeta?: (data: { request_id: string; redactions: Record<string, number> }) => void;
  onEmergency?: (data: Emergency[]) => void;
  onTools?: (data: ToolCard[]) => void;
  onSources?: (data: Source[]) => void;
  onToken?: (text: string) => void;
  onFinal?: (data: FinalResult) => void;
  onError?: (message: string) => void;
}

function compactContext(ctx: PatientContext): Partial<PatientContext> | undefined {
  const out: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(ctx)) {
    if (value === undefined || value === "" || (Array.isArray(value) && value.length === 0)) continue;
    out[key] = value;
  }
  return Object.keys(out).length ? (out as Partial<PatientContext>) : undefined;
}

/** Ask a question and consume the typed server sent event stream. */
export async function askStream(
  question: string,
  context: PatientContext,
  provider: Provider | undefined,
  historyInScope: boolean,
  handlers: StreamHandlers,
  signal?: AbortSignal,
): Promise<void> {
  const response = await fetch("/v1/ask/stream", {
    method: "POST",
    headers: headers(),
    body: JSON.stringify({ question, patient_context: compactContext(context), provider, history_in_scope: historyInScope }),
    signal,
  });
  if (!response.ok || !response.body) {
    handlers.onError?.(`Request failed with status ${response.status}`);
    return;
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let boundary = buffer.indexOf("\n\n");
    while (boundary !== -1) {
      const raw = buffer.slice(0, boundary);
      buffer = buffer.slice(boundary + 2);
      dispatch(raw, handlers);
      boundary = buffer.indexOf("\n\n");
    }
  }
}

function dispatch(raw: string, handlers: StreamHandlers): void {
  let event = "message";
  let data = "";
  for (const line of raw.split("\n")) {
    if (line.startsWith("event: ")) event = line.slice(7);
    else if (line.startsWith("data: ")) data += line.slice(6);
  }
  if (!data) return;
  const parsed = JSON.parse(data);
  switch (event) {
    case "meta":
      handlers.onMeta?.(parsed);
      break;
    case "emergency":
      handlers.onEmergency?.(parsed);
      break;
    case "tools":
      handlers.onTools?.(parsed);
      break;
    case "sources":
      handlers.onSources?.(parsed);
      break;
    case "token":
      handlers.onToken?.(parsed);
      break;
    case "final":
      handlers.onFinal?.(parsed);
      break;
  }
}

export async function sendFeedback(requestId: string, rating: string, reasons: string[], comment: string): Promise<boolean> {
  const response = await fetch("/v1/feedback", {
    method: "POST",
    headers: headers(),
    body: JSON.stringify({ request_id: requestId, rating, reasons, comment: comment || null }),
  });
  return response.ok;
}

export async function health(): Promise<{ index: { chunks: number; documents: number; origin: string } } | null> {
  try {
    const response = await fetch("/health");
    return response.ok ? response.json() : null;
  } catch {
    return null;
  }
}
