import type { ComponentType } from "react";
import { Link } from "react-router-dom";
import AnimatedNumber from "../components/AnimatedNumber";
import Delta from "../components/Delta";
import EmptyState from "../components/EmptyState";
import ErrorView from "../components/ErrorView";
import {
  IconCheck,
  IconChevronRight,
  IconClock,
  IconHeart,
  IconPosts,
  IconUsers,
} from "../components/icons";
import PostCard from "../components/PostCard";
import RankRow from "../components/RankRow";
import { Skeleton } from "../components/Skeleton";
import Sparkline from "../components/Sparkline";
import { useApi } from "../hooks/useApi";
import { hapticSelection } from "../telegram";
import type {
  ChannelStats,
  MeResponse,
  PostsListResponse,
  PostsStats,
  ReactionRow,
} from "../types";
import { formatNumber } from "../utils/format";

function Metric({
  icon: Icon,
  tint,
  value,
  label,
  loading,
}: {
  icon: ComponentType<{ size?: number }>;
  tint: string;
  value: number | undefined;
  label: string;
  loading: boolean;
}) {
  return (
    <div className="metric">
      <div
        className="metric__icon"
        style={{ background: `color-mix(in srgb, ${tint} 18%, transparent)`, color: tint }}
      >
        <Icon size={19} />
      </div>
      <div className="metric__value">
        {loading || value === undefined ? <Skeleton width={48} height={22} /> : (
          <AnimatedNumber value={value} />
        )}
      </div>
      <div className="metric__label">{label}</div>
    </div>
  );
}

export default function Dashboard() {
  const me = useApi<MeResponse>("/me");
  const channel = useApi<ChannelStats>("/channel/stats?days=7");
  const stats = useApi<PostsStats>("/posts/stats");
  const top = useApi<ReactionRow[]>("/posts/reactions/top?limit=50");
  const recent = useApi<PostsListResponse>("/posts?limit=3&offset=0");

  const snapshots = channel.data?.snapshots ?? [];
  const values = snapshots.map((s) => s.member_count);
  const memberCount = channel.data?.member_count ?? null;
  const growth =
    values.length >= 2 ? values[values.length - 1] - values[0] : null;

  const totalReactions = (top.data ?? []).reduce((acc, r) => acc + r.total_count, 0);
  const topThree = (top.data ?? []).slice(0, 3);

  const greeting = me.data?.first_name ? `Привет, ${me.data.first_name}` : "Обзор канала";

  return (
    <div className="page">
      <header className="page-header">
        <div>
          <div className="eyebrow">{greeting}</div>
          <h1 className="page-title">{channel.data?.title || "Дашборд"}</h1>
        </div>
      </header>

      {channel.error ? (
        <ErrorView error={channel.error} onRetry={channel.reload} />
      ) : (
        <div className="hero">
          <div className="hero__label">
            <IconUsers size={17} />
            Подписчики
          </div>
          <div className="hero__value">
            {channel.loading ? (
              <Skeleton width={140} height={44} />
            ) : memberCount === null ? (
              "—"
            ) : (
              <AnimatedNumber value={memberCount} />
            )}
          </div>
          {!channel.loading && (
            <div style={{ marginTop: 10 }}>
              <Delta value={growth} suffix="за неделю" />
            </div>
          )}
          {values.length >= 2 && (
            <div className="hero__chart">
              <Sparkline data={values} height={72} />
            </div>
          )}
        </div>
      )}

      <div className="metric-grid stagger" style={{ marginTop: "var(--space-3)" }}>
        <Metric
          icon={IconPosts}
          tint="var(--c-draft)"
          value={stats.data?.total}
          label="Всего постов"
          loading={stats.loading}
        />
        <Metric
          icon={IconCheck}
          tint="var(--c-published)"
          value={stats.data?.published}
          label="Опубликовано"
          loading={stats.loading}
        />
        <Metric
          icon={IconClock}
          tint="var(--c-publishing)"
          value={stats.data?.draft}
          label="Черновики"
          loading={stats.loading}
        />
        <Metric
          icon={IconHeart}
          tint="var(--c-rejected)"
          value={top.loading ? undefined : totalReactions}
          label="Реакции"
          loading={top.loading}
        />
      </div>

      <div className="section-head">
        <span className="section-head__title">Топ постов</span>
        <Link to="/reactions" className="section-head__link" onClick={hapticSelection}>
          Все <IconChevronRight />
        </Link>
      </div>
      {top.loading ? (
        <Skeleton height={72} radius={18} />
      ) : topThree.length === 0 ? (
        <div className="card muted text-sm">Пока нет постов с реакциями.</div>
      ) : (
        <div className="stack stagger">
          {topThree.map((row, i) => (
            <RankRow key={row.tg_message_id} row={row} rank={i + 1} />
          ))}
        </div>
      )}

      <div className="section-head">
        <span className="section-head__title">Последние посты</span>
        <Link to="/posts" className="section-head__link" onClick={hapticSelection}>
          Все <IconChevronRight />
        </Link>
      </div>
      {recent.error ? (
        <ErrorView error={recent.error} onRetry={recent.reload} />
      ) : recent.loading ? (
        <Skeleton height={96} radius={18} />
      ) : (recent.data?.items.length ?? 0) === 0 ? (
        <EmptyState title="Постов пока нет" subtitle="Сгенерируйте первый пост в боте." />
      ) : (
        <div className="stack stagger">
          {recent.data!.items.map((p) => (
            <PostCard key={p.id} post={p} />
          ))}
        </div>
      )}

      {memberCount !== null && snapshots.length > 0 && (
        <div className="muted text-xs" style={{ textAlign: "center", marginTop: 16 }}>
          {formatNumber(snapshots.length)} срезов за {channel.data?.days ?? 7} дней
        </div>
      )}
    </div>
  );
}
