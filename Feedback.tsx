import { useState } from "react";
import { sendFeedback } from "../api";

const REASONS: [string, string][] = [
  ["incorrect", "Incorrect"],
  ["outdated", "Outdated"],
  ["missing_source", "Missing source"],
  ["unsafe_dose", "Unsafe figure"],
  ["not_uk", "Not UK practice"],
  ["too_long", "Too long"],
];

export default function Feedback({ requestId }: { requestId: string }) {
  const [rating, setRating] = useState<string | null>(null);
  const [reasons, setReasons] = useState<string[]>([]);
  const [comment, setComment] = useState("");
  const [sent, setSent] = useState(false);

  if (sent) return <p className="muted feedback">Thank you. Feedback is reviewed by the clinical safety officer.</p>;

  const submit = async () => {
    if (!rating) return;
    if (await sendFeedback(requestId, rating, reasons, comment)) setSent(true);
  };

  return (
    <div className="feedback">
      <span>Was this useful?</span>
      {[
        ["helpful", "Helpful"],
        ["not_helpful", "Not helpful"],
        ["unsafe", "Unsafe"],
      ].map(([value, label]) => (
        <button key={value} className={rating === value ? "chip on" : "chip"} onClick={() => setRating(value)}>
          {label}
        </button>
      ))}
      {rating && rating !== "helpful" ? (
        <div className="feedback-detail">
          <div className="chips">
            {REASONS.map(([value, label]) => (
              <button
                key={value}
                className={reasons.includes(value) ? "chip on" : "chip"}
                onClick={() => setReasons(reasons.includes(value) ? reasons.filter((r) => r !== value) : [...reasons, value])}
              >
                {label}
              </button>
            ))}
          </div>
          <textarea placeholder="Optional comment (identifiers are redacted)" value={comment} onChange={(e) => setComment(e.target.value)} />
        </div>
      ) : null}
      {rating ? <button className="primary small" onClick={submit}>Send</button> : null}
    </div>
  );
}
