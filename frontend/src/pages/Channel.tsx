import { useState } from "react";
import AnimatedNumber from "../components/AnimatedNumber";
import Delta from "../components/Delta";
import ErrorView from "../components/ErrorView";
import { IconUsers } from "../components/icons";
import SegmentedControl from "../components/SegmentedControl";
import { Skeleton } from "../components/Skeleton";
import Sparkline from "../components/Sparkline";
import { useApi } from "../hooks/useApi";
import type { ChannelStats } from "../types";
import { formatDate, formatNumber } from "../utils/format";

type Days = "7" | "14" | "30";

const PERIODS: Array<{ value: Days; label: string }> = [
  { value: "7", label: "7 дней" },
  { value: "14", label: "14 дней" },
  { value: "30", label: "30 дней" },
];

export default function Channel() {
  const [days, setDays] = useState<Days>("7");
  const { data, error, loading, reload } = useApi<ChannelStats>(`/channel/stats?days=${days}`);

  const snapshots = data?.snapshots ?? [];
  const values = snapshots.map((s) => s.member_count);
  const memberCount = data?.member_count ?? null;
  const growth = values.length >= 2 ? values[values.length - 1] - values[0] : null;
  const peak = values.length ? Math.max(...values) : null;
  const low = values.length ? Math.min(...values) : null;

  return (
    <div className="page">
      <header className="page-header">
        <div>
          <div className="eyebrow">Аналитика канала</div>
          <h1 className="page-title">{data?.title || data?.channel_id || "Канал"}</h1>
        </div>
      </header>

      {error ? (
        <ErrorView error={error} onRetry={reload} />
      ) : (
        <>
          <SegmentedControl
            options={PERIODS}
            value={days}
            onChange={setDays}
          />

          <div className="hero" style={{ marginTop: "var(--space-3)" }}>
            <div className="hero__label">
              <IconUsers size={17} />
              Подписчики
            </div>
            <div className="hero__value">
              {loading ? (
                <Skeleton width={150} height={44} />
              ) : memberCount === null ? (
                "—"
              ) : (
                <AnimatedNumber value={memberCount} />
              )}
            </div>
            {!loading && (
              <div style={{ marginTop: 10 }}>
                <Delta value={growth} suffix={`за ${days} дн`} />
              </div>
            )}
            {values.length >= 2 && (
              <div className="hero__chart">
                <Sparkline data={values} height={96} />
              </div>
            )}
          </div>

          {!loading && values.length >= 2 && (
            <div className="metric-grid" style={{ marginTop: "var(--space-3)" }}>
              <div className="metric">
                <div className="metric__value">{peak !== null ? formatNumber(peak) : "—"}</div>
                <div className="metric__label">Максимум за период</div>
              </div>
              <div className="metric">
                <div className="metric__value">{low !== null ? formatNumber(low) : "—"}</div>
                <div className="metric__label">Минимум за период</div>
              </div>
            </div>
          )}

          {snapshots.length > 0 && (
            <div
              className="muted text-xs"
              style={{ display: "flex", justifyContent: "space-between", marginTop: 14 }}
            >
              <span>{formatDate(snapshots[0].ts)}</span>
              <span>
                {formatNumber(snapshots.length)} срезов
              </span>
              <span>{formatDate(snapshots[snapshots.length - 1].ts)}</span>
            </div>
          )}

          {!loading && snapshots.length < 2 && (
            <div className="card muted text-sm" style={{ marginTop: 14 }}>
              Недостаточно данных для графика — снимки накапливаются по расписанию.
            </div>
          )}
        </>
      )}
    </div>
  );
}
