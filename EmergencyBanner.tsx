import type { Emergency } from "../types";

export default function EmergencyBanner({ alerts }: { alerts: Emergency[] }) {
  if (!alerts.length) return null;
  return (
    <section className="emergency" role="alert" aria-live="assertive">
      {alerts.map((alert) => (
        <div key={alert.category} className="emergency-item">
          <h3>{alert.title}</h3>
          <ol>
            {alert.actions.map((action) => (
              <li key={action}>{action}</li>
            ))}
          </ol>
          <p className="emergency-guidance">{alert.guidance.join(" · ")}</p>
        </div>
      ))}
    </section>
  );
}
