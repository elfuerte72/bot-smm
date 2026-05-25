import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api";
import ErrorView from "../components/ErrorView";
import PostCard from "../components/PostCard";
import Spinner from "../components/Spinner";
import type { PostsListResponse, PostsStats, PostStatus } from "../types";

const LIMIT = 20;

const STATUS_FILTERS: Array<{ value: PostStatus | "all"; label: string }> = [
  { value: "all", label: "Все" },
  { value: "draft", label: "Драфты" },
  { value: "published", label: "Опубликованные" },
  { value: "rejected", label: "Отклонённые" },
];

const PERIOD_FILTERS: Array<{ value: "24h" | "7d" | "30d" | "all"; label: string }> = [
  { value: "all", label: "Всё время" },
  { value: "24h", label: "24ч" },
  { value: "7d", label: "7 дней" },
  { value: "30d", label: "30 дней" },
];

export default function Posts() {
  const [stats, setStats] = useState<PostsStats | null>(null);
  const [statsError, setStatsError] = useState<unknown>(null);

  const [statusFilter, setStatusFilter] = useState<PostStatus | "all">("all");
  const [period, setPeriod] = useState<"24h" | "7d" | "30d" | "all">("all");
  const [searchInput, setSearchInput] = useState("");
  const [search, setSearch] = useState("");
  const [offset, setOffset] = useState(0);

  const [data, setData] = useState<PostsListResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<unknown>(null);

  // Дебаунс поискового ввода
  const debounceRef = useRef<number | null>(null);
  useEffect(() => {
    if (debounceRef.current) {
      window.clearTimeout(debounceRef.current);
    }
    debounceRef.current = window.setTimeout(() => {
      setSearch(searchInput.trim());
      setOffset(0);
    }, 300);
    return () => {
      if (debounceRef.current) {
        window.clearTimeout(debounceRef.current);
      }
    };
  }, [searchInput]);

  useEffect(() => {
    api<PostsStats>("/posts/stats").then(setStats).catch(setStatsError);
  }, []);

  const queryString = useMemo(() => {
    const params = new URLSearchParams();
    if (statusFilter !== "all") params.set("status", statusFilter);
    params.set("period", period);
    if (search) params.set("search", search);
    params.set("offset", String(offset));
    params.set("limit", String(LIMIT));
    return params.toString();
  }, [statusFilter, period, search, offset]);

  useEffect(() => {
    setLoading(true);
    setError(null);
    api<PostsListResponse>(`/posts?${queryString}`)
      .then((d) => {
        setData(d);
        setLoading(false);
      })
      .catch((e) => {
        setError(e);
        setLoading(false);
      });
  }, [queryString]);

  const hasPrev = offset > 0;
  const hasNext = data ? offset + LIMIT < data.total : false;

  return (
    <div>
      <h2 style={{ margin: "0 0 12px" }}>Посты</h2>

      {statsError ? (
        <ErrorView error={statsError} />
      ) : stats ? (
        <div className="card" style={{ display: "flex", gap: 16, flexWrap: "wrap" }}>
          <span>Всего: <strong>{stats.total}</strong></span>
          <span className="muted">draft: {stats.draft}</span>
          <span className="muted">published: {stats.published}</span>
          <span className="muted">rejected: {stats.rejected}</span>
          {stats.publishing > 0 && <span className="muted">publishing: {stats.publishing}</span>}
        </div>
      ) : (
        <div className="card"><Spinner /></div>
      )}

      <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 12 }}>
        {STATUS_FILTERS.map((f) => (
          <button
            key={f.value}
            onClick={() => {
              setStatusFilter(f.value);
              setOffset(0);
            }}
            className={statusFilter === f.value ? "nav__link nav__link--active" : "nav__link"}
          >
            {f.label}
          </button>
        ))}
      </div>

      <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 12 }}>
        {PERIOD_FILTERS.map((f) => (
          <button
            key={f.value}
            onClick={() => {
              setPeriod(f.value);
              setOffset(0);
            }}
            className={period === f.value ? "nav__link nav__link--active" : "nav__link"}
          >
            {f.label}
          </button>
        ))}
      </div>

      <input
        value={searchInput}
        onChange={(e) => setSearchInput(e.target.value)}
        placeholder="Поиск по заголовку..."
        style={{
          width: "100%",
          padding: "10px 12px",
          borderRadius: "var(--radius-md)",
          background: "var(--tg-secondary-bg)",
          border: "none",
          color: "var(--tg-text)",
          marginBottom: 12,
        }}
        aria-label="Поиск"
      />

      {error != null && <ErrorView error={error} />}
      {loading && (
        <div style={{ textAlign: "center", padding: 20 }}>
          <Spinner />
        </div>
      )}

      {data && !loading && (
        <>
          {data.items.length === 0 ? (
            <div className="card muted">Ничего не найдено.</div>
          ) : (
            <div>
              {data.items.map((p) => (
                <PostCard key={p.id} post={p} />
              ))}
            </div>
          )}

          {(hasPrev || hasNext) && (
            <div style={{ display: "flex", justifyContent: "space-between", gap: 8 }}>
              <button
                onClick={() => setOffset(Math.max(0, offset - LIMIT))}
                disabled={!hasPrev}
                className="nav__link"
                style={{ opacity: hasPrev ? 1 : 0.4 }}
              >
                ← Назад
              </button>
              <span className="muted" style={{ alignSelf: "center", fontSize: 13 }}>
                {offset + 1}–{Math.min(offset + LIMIT, data.total)} из {data.total}
              </span>
              <button
                onClick={() => setOffset(offset + LIMIT)}
                disabled={!hasNext}
                className="nav__link"
                style={{ opacity: hasNext ? 1 : 0.4 }}
              >
                Дальше →
              </button>
            </div>
          )}
        </>
      )}
    </div>
  );
}
