import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import ErrorView from "../components/ErrorView";
import Spinner from "../components/Spinner";
import type { ReactionRow } from "../types";

function formatDate(iso: string | null): string {
  if (!iso) return "";
  const d = new Date(iso.includes("T") ? iso : iso.replace(" ", "T") + "Z");
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString("ru-RU", { day: "2-digit", month: "short" });
}

function ReactionItem({ row }: { row: ReactionRow }) {
  const inner = (
    <div className="card" style={{ display: "block" }}>
      <div style={{ display: "flex", justifyContent: "space-between", gap: 8, marginBottom: 6 }}>
        <strong style={{ fontSize: 22 }}>{row.total_count}</strong>
        {row.published_at && (
          <span className="muted" style={{ fontSize: 12, alignSelf: "flex-end" }}>
            {formatDate(row.published_at)}
          </span>
        )}
      </div>
      <div style={{ fontSize: 14, marginBottom: 6 }}>{row.title}</div>
      {row.reactions.length > 0 && (
        <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
          {row.reactions.map((r) => (
            <span key={r.emoji} style={{ fontSize: 13 }}>
              <span style={{ fontSize: 16 }}>{r.emoji}</span>
              <span className="muted"> ×{r.count}</span>
            </span>
          ))}
        </div>
      )}
    </div>
  );

  if (row.draft_id != null) {
    return (
      <Link
        to={`/posts/${row.draft_id}`}
        style={{ display: "block", textDecoration: "none", color: "inherit" }}
      >
        {inner}
      </Link>
    );
  }
  return inner;
}

type Mode = "top" | "bottom";

const TABS: Array<{ mode: Mode; label: string }> = [
  { mode: "top", label: "Топ-10" },
  { mode: "bottom", label: "Анти-топ" },
];

export default function Reactions() {
  const [mode, setMode] = useState<Mode>("top");
  const [data, setData] = useState<ReactionRow[] | null>(null);
  const [error, setError] = useState<unknown>(null);

  useEffect(() => {
    setData(null);
    setError(null);
    api<ReactionRow[]>(`/posts/reactions/${mode}?limit=10`)
      .then(setData)
      .catch(setError);
  }, [mode]);

  return (
    <div>
      <h2 style={{ margin: "0 0 12px" }}>Реакции</h2>

      <div style={{ display: "flex", gap: 8, marginBottom: 12 }}>
        {TABS.map((t) => (
          <button
            key={t.mode}
            onClick={() => setMode(t.mode)}
            className={mode === t.mode ? "nav__link nav__link--active" : "nav__link"}
          >
            {t.label}
          </button>
        ))}
      </div>

      {error != null && <ErrorView error={error} />}
      {!data && !error && (
        <div style={{ textAlign: "center", padding: 20 }}>
          <Spinner />
        </div>
      )}
      {data && data.length === 0 && (
        <div className="card muted">
          {mode === "bottom"
            ? "Нет постов старше 24ч с собранными реакциями."
            : "Нет постов с реакциями."}
        </div>
      )}
      {data && data.map((row) => <ReactionItem key={row.tg_message_id} row={row} />)}
    </div>
  );
}
