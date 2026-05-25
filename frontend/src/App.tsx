import { useEffect, useState } from "react";
import { api, ApiError } from "./api";
import { tg } from "./telegram";

interface HealthResponse {
  status: string;
  db: string;
}

export default function App() {
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api<HealthResponse>("/health")
      .then(setHealth)
      .catch((e: unknown) => {
        if (e instanceof ApiError) {
          setError(`${e.status}: ${e.body}`);
          if (e.status === 401 || e.status === 403) {
            tg?.close();
          }
        } else {
          setError(String(e));
        }
      });
  }, []);

  return (
    <div className="app">
      <h1>SMM Bot — Stats</h1>
      <p className="muted">Frontend bootstrap страница. Полные страницы появятся в Task 10.</p>
      <div className="card">
        <strong>Backend health:</strong>{" "}
        {error ? (
          <span className="error">{error}</span>
        ) : health ? (
          <code>
            {health.status} / db={health.db}
          </code>
        ) : (
          <span className="spinner" aria-label="loading" />
        )}
      </div>
    </div>
  );
}
