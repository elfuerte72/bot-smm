import { useState } from "react";
import EmptyState from "../components/EmptyState";
import ErrorView from "../components/ErrorView";
import { IconHeart } from "../components/icons";
import RankRow from "../components/RankRow";
import SegmentedControl from "../components/SegmentedControl";
import { Skeleton } from "../components/Skeleton";
import { useApi } from "../hooks/useApi";
import type { ReactionRow } from "../types";

type Mode = "top" | "bottom";

const MODES: Array<{ value: Mode; label: string }> = [
  { value: "top", label: "Топ-10" },
  { value: "bottom", label: "Анти-топ" },
];

export default function Reactions() {
  const [mode, setMode] = useState<Mode>("top");
  const { data, error, loading, reload } = useApi<ReactionRow[]>(
    `/posts/reactions/${mode}?limit=10`,
  );

  return (
    <div className="page">
      <header className="page-header">
        <div>
          <div className="eyebrow">Вовлечённость</div>
          <h1 className="page-title">Реакции</h1>
        </div>
      </header>

      <SegmentedControl options={MODES} value={mode} onChange={setMode} />

      <div style={{ marginTop: "var(--space-4)" }}>
        {error ? (
          <ErrorView error={error} onRetry={reload} />
        ) : loading ? (
          <div className="stack">
            {Array.from({ length: 5 }, (_, i) => (
              <Skeleton key={i} height={78} radius={18} />
            ))}
          </div>
        ) : data && data.length === 0 ? (
          <EmptyState
            icon={<IconHeart size={24} />}
            title={mode === "bottom" ? "Нет подходящих постов" : "Пока нет реакций"}
            subtitle={
              mode === "bottom"
                ? "Анти-топ показывает посты старше 24 часов."
                : "Реакции появятся после публикации постов."
            }
          />
        ) : (
          data && (
            <div className="stack stagger">
              {data.map((row, i) => (
                <RankRow
                  key={row.tg_message_id}
                  row={row}
                  rank={i + 1}
                  highlight={mode === "top"}
                />
              ))}
            </div>
          )
        )}
      </div>
    </div>
  );
}
