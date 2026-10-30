import { useState } from "react";
import { Link, Outlet } from "react-router-dom";
import { getApiKey, setApiKey, SIGN_IN_OPTIONS } from "./api";

// The frame around every page: title, who you are signed in as.
export default function App() {
  const [apiKey, setKey] = useState(getApiKey());
  const signedInAs = SIGN_IN_OPTIONS.find((o) => o.key === apiKey)?.label ?? "Custom key";

  function change(key: string) {
    setApiKey(key);
    setKey(key);
    window.location.reload(); // simplest way to refetch everything with the new key
  }

  return (
    <>
      <header className="topbar">
        <Link to="/" className="brand">
          Sourcing Copilot
        </Link>
        <label className="signin">
          Signed in as
          <select value={apiKey} onChange={(e) => change(e.target.value)} data-testid="sign-in">
            {SIGN_IN_OPTIONS.map((o) => (
              <option key={o.key} value={o.key}>
                {o.label}
              </option>
            ))}
          </select>
          <span className="muted">({signedInAs})</span>
        </label>
      </header>
      <main className="page">
        <Outlet />
      </main>
    </>
  );
}
