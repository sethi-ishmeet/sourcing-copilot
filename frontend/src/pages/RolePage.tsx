import { useEffect, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import {
  api,
  describeError,
  getApiKey,
  SIGN_IN_OPTIONS,
  type DataChecks,
  type Role,
  type RoleSummary,
} from "../api";
import { StatusBadge } from "../components";

// Screen one: pick a role, see its shortlist, start a screening.
export default function RolePage() {
  const [roles, setRoles] = useState<RoleSummary[]>([]);
  const [role, setRole] = useState<Role | null>(null);
  const [checks, setChecks] = useState<DataChecks | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [screening, setScreening] = useState<string | null>(null); // candidate id in progress
  const [params, setParams] = useSearchParams();
  const navigate = useNavigate();
  const roleId = params.get("role");

  useEffect(() => {
    api.roles()
      .then((list) => {
        setRoles(list);
        if (!roleId && list.length) setParams({ role: list[0].id }, { replace: true });
      })
      .catch((e) => setError(describeError(e)));
    api.dataChecks().then(setChecks).catch(() => setChecks(null));
  }, [roleId, setParams]);

  useEffect(() => {
    if (!roleId) return;
    api.role(roleId).then(setRole).catch((e) => setError(describeError(e)));
  }, [roleId]);

  async function startScreening(candidateId: string) {
    setScreening(candidateId);
    setError(null);
    try {
      const result = await api.startScreening(roleId!, candidateId);
      navigate(`/screenings/${result.run_id}`);
    } catch (e) {
      setError(describeError(e));
      setScreening(null);
    }
  }

  const isViewer = SIGN_IN_OPTIONS.find((o) => o.key === getApiKey())?.label === "Viewer";

  if (!role && error) return <p className="error">{error}</p>;
  if (!role) return <p className="muted">Loading…</p>;

  return (
    <>
      {error && (
        <p className="error" data-testid="page-error">
          {error}
        </p>
      )}
      <div className="row space-between">
        <div>
          <h1>
            {role.title} <span className="muted">at {role.company}</span>
          </h1>
          <p className="muted">{role.location}</p>
        </div>
        {roles.length > 1 && (
          <label>
            Role{" "}
            <select value={role.id} onChange={(e) => setParams({ role: e.target.value })}>
              {roles.map((r) => (
                <option key={r.id} value={r.id}>
                  {r.title}
                </option>
              ))}
            </select>
          </label>
        )}
      </div>

      <section className="card">
        <p>{role.description}</p>
        <h3>Requirements</h3>
        <ul className="requirements">
          {role.requirements.map((r) => (
            <li key={r.id}>
              {r.text} {r.must_have && <span className="tag">must have</span>}
            </li>
          ))}
        </ul>
      </section>

      <section className="card">
        <div className="row space-between">
          <h3>Shortlist ({role.candidates.length})</h3>
          {checks && (
            <span className="muted" data-testid="data-checks">
              Data checks: {checks.errors} errors, {checks.warnings} warnings
            </span>
          )}
        </div>
        <table data-testid="shortlist">
          <thead>
            <tr>
              <th>Candidate</th>
              <th>Current job</th>
              <th>Years</th>
              <th>Notes</th>
              <th>Latest screening</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {role.candidates.map((c) => (
              <tr key={c.id} data-testid={`candidate-${c.id}`}>
                <td>
                  <strong>{c.full_name}</strong>
                  <div className="muted small">{c.location}</div>
                </td>
                <td>
                  {c.current_title ?? "—"}
                  <div className="muted small">{c.current_company ?? ""}</div>
                </td>
                <td>{c.years_of_experience}</td>
                <td className="small">
                  {c.data_warnings.map((w) => (
                    <div key={w} className="warning">
                      {w}
                    </div>
                  ))}
                </td>
                <td>
                  {c.latest_screening ? (
                    <Link to={`/screenings/${c.latest_screening.run_id}`}>
                      <StatusBadge status={c.latest_screening.status} />
                    </Link>
                  ) : (
                    <span className="muted">not screened</span>
                  )}
                </td>
                <td>
                  <button
                    onClick={() => startScreening(c.id)}
                    disabled={screening !== null || isViewer}
                    title={isViewer ? "Only a recruiter can start a screening" : undefined}
                    data-testid={`screen-${c.id}`}
                  >
                    {screening === c.id ? "Screening…" : "Screen"}
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    </>
  );
}
