import { useEffect, useMemo, useRef, useState } from "react";
import EmptyState from "../components/EmptyState";
import ErrorView from "../components/ErrorView";
import { IconSearch } from "../components/icons";
import PostCard from "../components/PostCard";
import SegmentedControl from "../components/SegmentedControl";
import { PostListSkeleton } from "../components/Skeleton";
import { useApi } from "../hooks/useApi";
import { hapticSelection } from "../telegram";
import type { PostsListResponse, PostsStats, PostStatus } from "../types";

const LIMIT = 20;

type StatusFilter = PostStatus | "all";
type Period = "24h" | "7d" | "30d" | "all";

const STATUS_FILTERS: Array<{ value: StatusFilter; label: string }> = [
  { value: "all", label: "Все" },
  { value: "draft", label: "Черновики" },
  { value: "published", label: "Готовые" },
  { value: "rejected", label: "Отклонённые" },
];

const PERIOD_FILTERS: Array<{ value: Period; label: string }> = [
  { value: "all", label: "Всё время" },
  { value: "24h", label: "24ч" },
  { value: "7d", label: "7 дней" },
  { value: "30d", label: "30 дней" },
];

export default function Posts() {
  const stats = useApi<PostsStats>("/posts/stats");

  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");
  const [period, setPeriod] = useState<Period>("all");
  const [searchInput, setSearchInput] = useState("");
  const [search, setSearch] = useState("");
  const [offset, setOffset] = useState(0);

  const debounceRef = useRef<number | null>(null);
  useEffect(() => {
    if (debounceRef.current) window.clearTimeout(debounceRef.current);
    debounceRef.current = window.setTimeout(() => {
      setSearch(searchInput.trim());
      setOffset(0);
    }, 300);
    return () => {
      if (debounceRef.current) window.clearTimeout(debounceRef.current);
    };
  }, [searchInput]);

  const queryString = useMemo(() => {
    const params = new URLSearchParams();
    if (statusFilter !== "all") params.set("status", statusFilter);
    params.set("period", period);
    if (search) params.set("search", search);
    params.set("offset", String(offset));
    params.set("limit", String(LIMIT));
    return params.toString();
  }, [statusFilter, period, search, offset]);

  const { data, error, loading, reload } = useApi<PostsListResponse>(`/posts?${queryString}`);

  const hasPrev = offset > 0;
  const hasNext = data ? offset + LIMIT < data.total : false;

  return (
    <div className="page">
      <header className="page-header">
        <div>
          <h1 className="page-title">Посты</h1>
          {stats.data && (
            <div className="page-subtitle">
              {stats.data.total} всего · {stats.data.published} опубликовано ·{" "}
              {stats.data.draft} черновиков
            </div>
          )}
        </div>
      </header>

      <div className="stack" style={{ marginBottom: "var(--space-3)" }}>
        <SegmentedControl
          options={STATUS_FILTERS}
          value={statusFilter}
          onChange={(v) => {
            setStatusFilter(v);
            setOffset(0);
          }}
        />
        <div className="chips no-scrollbar">
          {PERIOD_FILTERS.map((f) => (
            <button
              key={f.value}
              onClick={() => {
                hapticSelection();
                setPeriod(f.value);
                setOffset(0);
              }}
              className={period === f.value ? "chip chip--active" : "chip"}
            >
              {f.label}
            </button>
          ))}
        </div>
      </div>

      <div className="search">
        <span className="search__icon">
          <IconSearch />
        </span>
        <input
          value={searchInput}
          onChange={(e) => setSearchInput(e.target.value)}
          placeholder="Поиск по заголовку"
          className="search__input"
          aria-label="Поиск"
        />
      </div>

      {error ? (
        <ErrorView error={error} onRetry={reload} />
      ) : loading ? (
        <PostListSkeleton />
      ) : data && data.items.length === 0 ? (
        <EmptyState
          title="Ничего не найдено"
          subtitle="Попробуйте изменить фильтры или поиск."
        />
      ) : (
        data && (
          <>
            <div className="stack stagger">
              {data.items.map((p) => (
                <PostCard key={p.id} post={p} />
              ))}
            </div>

            {(hasPrev || hasNext) && (
              <div className="pager">
                <button
                  onClick={() => {
                    hapticSelection();
                    setOffset(Math.max(0, offset - LIMIT));
                  }}
                  disabled={!hasPrev}
                  className="pager__btn"
                >
                  ← Назад
                </button>
                <span className="pager__info">
                  {offset + 1}–{Math.min(offset + LIMIT, data.total)} из {data.total}
                </span>
                <button
                  onClick={() => {
                    hapticSelection();
                    setOffset(offset + LIMIT);
                  }}
                  disabled={!hasNext}
                  className="pager__btn"
                >
                  Дальше →
                </button>
              </div>
            )}
          </>
        )
      )}
    </div>
  );
}
