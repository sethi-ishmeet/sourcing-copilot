import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, describeError, type Screening, type Trace } from "../api";
import { Score, StatusBadge } from "../components";

// Screen two: one screening. The scorecard with proof, the draft, approve/edit/reject,
// then what happened, step by step.
export default function ScreeningPage() {
  const { runId } = useParams<{ runId: string }>();
  const [screening, setScreening] = useState<Screening | null>(null);
  const [trace, setTrace] = useState<Trace | null>(null);
  const [message, setMessage] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    const [s, t] = await Promise.all([api.screening(runId!), api.trace(runId!)]);
    setScreening(s);
    setTrace(t);
    setMessage(s.draft_message ?? "");
  }, [runId]);

  useEffect(() => {
    load().catch((e) => setError(describeError(e)));
  }, [load]);

  async function decide(action: "approve" | "reject") {
    setBusy(true);
    setError(null);
    try {
      const edited = message.trim() !== (screening?.draft_message ?? "").trim() ? message : undefined;
      await api.decide(runId!, action, action === "approve" ? edited : undefined);
      await load();
    } catch (e) {
      setError(describeError(e));
    } finally {
      setBusy(false);
    }
  }

  if (error && !screening) return <p className="error">{error}</p>;
  if (!screening) return <p className="muted">Loading…</p>;

  const card = screening.scorecard;
  const waiting = screening.status === "awaiting_approval";
  const requirementText = (id: string) =>
    screening.requirements.find((r) => r.id === id)?.text ?? id;
  const mustHave = (id: string) => screening.requirements.find((r) => r.id === id)?.must_have;

  return (
    <>
      <p>
        <Link to={`/?role=${screening.role_id}`}>← Back to {screening.role_title}</Link>
      </p>
      <div className="row space-between">
        <h1>
          {screening.candidate_name} <span className="muted">for {screening.role_title}</span>
        </h1>
        <StatusBadge status={screening.status} />
      </div>

      {screening.error && (
        <p className="error" data-testid="run-error">
          {screening.error}
        </p>
      )}
      {screening.data_warnings.map((w) => (
        <p key={w} className="warning">
          {w}
        </p>
      ))}

      {card && (
        <section className="card" data-testid="scorecard">
          <div className="row space-between">
            <h3>Scorecard</h3>
            <span className="muted">
              {card.recommend ? "Recommended" : "Not recommended"} · confidence {card.confidence}
            </span>
          </div>
          <p>{card.summary}</p>
          {card.warnings.map((w) => (
            <p key={w} className="warning">
              {w}
            </p>
          ))}
          <table>
            <thead>
              <tr>
                <th>Requirement</th>
                <th>Score</th>
                <th>Reason</th>
                <th>Proof from the profile</th>
              </tr>
            </thead>
            <tbody>
              {card.scores.map((s) => (
                <tr key={s.requirement_id} data-testid="score-row">
                  <td>
                    {requirementText(s.requirement_id)}{" "}
                    {mustHave(s.requirement_id) && <span className="tag">must have</span>}
                  </td>
                  <td>
                    <Score value={s.score} />
                  </td>
                  <td>{s.reason}</td>
                  <td className="quote">{s.proof ? `“${s.proof}”` : <span className="muted">none</span>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}

      {(screening.draft_message || screening.final_message) && (
        <section className="card" data-testid="message">
          <h3>{screening.status === "sent" ? "Message sent" : "Draft message"}</h3>
          {waiting ? (
            <>
              <textarea
                value={message}
                onChange={(e) => setMessage(e.target.value)}
                rows={5}
                data-testid="draft"
              />
              <div className="row space-between">
                <span className="muted small">
                  {message.length} characters. You can edit before approving; the same rules apply.
                </span>
                <span>
                  <button className="secondary" onClick={() => decide("reject")} disabled={busy} data-testid="reject">
                    Reject
                  </button>{" "}
                  <button onClick={() => decide("approve")} disabled={busy} data-testid="approve">
                    {busy ? "Working…" : "Approve and send"}
                  </button>
                </span>
              </div>
              {error && <p className="error">{error}</p>}
            </>
          ) : (
            <>
              <blockquote data-testid="final-message">{screening.final_message ?? screening.draft_message}</blockquote>
              {screening.decision && (
                <p className="muted small">
                  {screening.decision.action === "approve" ? "Approved" : "Rejected"} by {screening.decision.decided_by}{" "}
                  at {screening.decision.decided_at}
                  {screening.send_receipt &&
                    ` · sent as ${screening.send_receipt.message_id} after ${screening.send_receipt.attempts} attempt(s)`}
                </p>
              )}
            </>
          )}
        </section>
      )}

      {screening.rule_results.length > 0 && (
        <section className="card">
          <h3>Rules checked by code</h3>
          <ul className="rules">
            {screening.rule_results.map((r, i) => (
              <li key={`${r.rule}-${i}`} className={r.passed ? "ok" : "bad"}>
                {r.passed ? "✓" : "✗"} {r.rule.replaceAll("_", " ")}
                {!r.passed && <span className="muted"> — {r.detail}</span>}
              </li>
            ))}
          </ul>
        </section>
      )}

      {trace && (
        <section className="card">
          <div className="row space-between">
            <h3>What the copilot did</h3>
            <span className="muted small">
              {screening.tokens_in + screening.tokens_out} tokens · started by {screening.started_by}
            </span>
          </div>
          <ol className="steps" data-testid="steps">
            {trace.steps.map((s) => (
              <li key={s.seq} className={s.status === "error" ? "bad" : ""}>
                <details>
                  <summary>
                    <span className="step-name">{s.name}</span>
                    <span className="muted small">
                      {s.ms} ms{s.tokens_in + s.tokens_out > 0 ? ` · ${s.tokens_in + s.tokens_out} tokens` : ""}
                      {s.status === "error" ? " · error" : ""}
                    </span>
                  </summary>
                  <pre>{JSON.stringify(s.details, null, 2)}</pre>
                </details>
              </li>
            ))}
          </ol>
          <h3>Audit log</h3>
          <ul className="audit" data-testid="audit">
            {trace.audit.map((a, i) => (
              <li key={i}>
                <span className="muted small">{a.at}</span> <strong>{a.actor}</strong> {a.action}
                {a.detail && <span className="muted"> — {a.detail}</span>}
              </li>
            ))}
          </ul>
        </section>
      )}
    </>
  );
}
