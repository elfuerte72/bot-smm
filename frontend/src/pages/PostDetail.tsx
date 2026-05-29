import { Link, useNavigate, useParams } from "react-router-dom";
import ErrorView from "../components/ErrorView";
import { IconBack, IconClock, IconHeart, IconLink } from "../components/icons";
import ReactionChips from "../components/ReactionChips";
import { Skeleton } from "../components/Skeleton";
import StatusBadge from "../components/StatusBadge";
import { useApi } from "../hooks/useApi";
import { useBackButton } from "../hooks/useBackButton";
import { tg } from "../telegram";
import type { DraftEvent, PostDetailResponse, PostStatus } from "../types";
import { formatDateTime } from "../utils/format";

const EVENT_LABEL: Record<DraftEvent["event_type"], string> = {
  created: "Создан",
  edited: "Отредактирован",
  regenerated_from: "Перегенерирован",
  approved: "Одобрен",
  rejected: "Отклонён",
};

function EventPayload({ ev }: { ev: DraftEvent }) {
  const p = ev.payload;
  if (ev.event_type === "edited" && typeof p.diff_unified === "string") {
    return <DiffBlock diff={p.diff_unified} />;
  }
  if (ev.event_type === "created") {
    return (
      <div className="text-sm muted" style={{ marginTop: 4 }}>
        <div>
          режим: <code>{String(p.mode ?? "—")}</code>
        </div>
        {typeof p.topic === "string" && <div>тема: {p.topic}</div>}
        {typeof p.source_url === "string" && (
          <div style={{ wordBreak: "break-all" }}>{p.source_url}</div>
        )}
      </div>
    );
  }
  if (ev.event_type === "regenerated_from" && typeof p.new_draft_id === "number") {
    return (
      <div className="text-sm" style={{ marginTop: 4 }}>
        <Link to={`/posts/${p.new_draft_id}`}>
          → новый драфт #{p.new_draft_id}
          {typeof p.new_title === "string" ? `: ${p.new_title}` : ""}
        </Link>
      </div>
    );
  }
  if (ev.event_type === "approved") {
    return (
      <div className="text-sm muted" style={{ marginTop: 4 }}>
        {typeof p.channel_id === "string" && <div>канал: {p.channel_id}</div>}
        {typeof p.tg_message_id === "number" && <div>сообщение: {p.tg_message_id}</div>}
      </div>
    );
  }
  if (ev.event_type === "rejected" && typeof p.reason === "string") {
    return (
      <div className="text-sm muted" style={{ marginTop: 4 }}>
        причина: {p.reason}
      </div>
    );
  }
  return null;
}

function DiffBlock({ diff }: { diff: string }) {
  return (
    <pre className="diff">
      {diff.split("\n").map((line, i) => {
        let cls: string | undefined;
        if (line.startsWith("+") && !line.startsWith("+++")) cls = "diff__add";
        else if (line.startsWith("-") && !line.startsWith("---")) cls = "diff__del";
        else if (line.startsWith("@@")) cls = "diff__hunk";
        return (
          <span key={i} className={cls} style={cls ? undefined : { display: "block" }}>
            {line || "​"}
          </span>
        );
      })}
    </pre>
  );
}

function DetailSkeleton() {
  return (
    <div className="page">
      <Skeleton width="70%" height={26} style={{ marginBottom: 12 }} />
      <Skeleton width={180} height={14} style={{ marginBottom: 20 }} />
      <div className="card">
        <Skeleton height={14} style={{ marginBottom: 8 }} />
        <Skeleton height={14} style={{ marginBottom: 8 }} />
        <Skeleton width="85%" height={14} style={{ marginBottom: 8 }} />
        <Skeleton width="60%" height={14} />
      </div>
    </div>
  );
}

export default function PostDetail() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  useBackButton();

  const { data, error, reload } = useApi<PostDetailResponse>(
    id ? `/posts/${encodeURIComponent(id)}` : null,
  );

  if (error) {
    return (
      <div className="page">
        <ErrorView error={error} onRetry={reload} />
      </div>
    );
  }
  if (!data) return <DetailSkeleton />;

  const { post, events, reactions } = data;

  return (
    <div className="page">
      {/* В Telegram навигацию даёт нативная BackButton; вне его — текстовая. */}
      {!tg && (
        <button
          onClick={() => navigate(-1)}
          className="linkrow muted"
          style={{ marginBottom: 12 }}
        >
          <IconBack /> Назад
        </button>
      )}

      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 8 }}>
        <StatusBadge status={post.status as PostStatus | null} />
        <span className="muted text-xs">#{post.id}</span>
      </div>
      <h1 className="page-title" style={{ fontSize: 23, marginBottom: 8 }}>
        {post.title}
      </h1>
      <div className="muted text-sm" style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 16 }}>
        <IconClock size={14} />
        {formatDateTime(post.created_at)}
      </div>

      {post.tg_channel_url && (
        <a
          href={post.tg_channel_url}
          target="_blank"
          rel="noreferrer"
          className="card tappable linkrow"
          style={{ color: "var(--accent)" }}
        >
          <IconLink />
          Открыть в Telegram-канале
        </a>
      )}

      {post.primary_source_url && (
        <a
          href={post.primary_source_url}
          target="_blank"
          rel="noreferrer"
          className="card tappable"
        >
          <div className="linkrow">
            <IconLink />
            Источник
          </div>
          <div className="linkrow__url" style={{ marginTop: 4 }}>
            {post.primary_source_url}
          </div>
        </a>
      )}

      <div
        className="card post-body"
        // formatted_text — HTML-payload для Telegram (<b>, <a>, <code>,
        // <blockquote>), наш SYSTEM_PROMPT после антибот-фильтров и валидации.
        // Внутренний инструмент — dangerouslySetInnerHTML допустим.
        dangerouslySetInnerHTML={{ __html: post.formatted_text || post.preview || "(пусто)" }}
      />

      {reactions && reactions.reactions.length > 0 && (
        <div className="card">
          <div style={{ display: "flex", alignItems: "center", gap: 6, fontWeight: 700 }}>
            <IconHeart size={16} />
            Реакции · {reactions.total_count}
          </div>
          <ReactionChips reactions={reactions.reactions} />
          {reactions.updated_at && (
            <div className="muted text-xs" style={{ marginTop: 8 }}>
              обновлено {formatDateTime(reactions.updated_at)}
            </div>
          )}
        </div>
      )}

      <div className="section-head">
        <span className="section-head__title">История</span>
      </div>
      {events.length === 0 ? (
        <div className="card muted text-sm">Событий нет.</div>
      ) : (
        <div className="card">
          <div className="timeline">
            {events.map((ev) => (
              <div key={ev.id} className="timeline__item">
                <span className="timeline__dot" />
                <div className="timeline__head">
                  <span className="timeline__type">{EVENT_LABEL[ev.event_type]}</span>
                  <span className="timeline__time">{formatDateTime(ev.created_at)}</span>
                </div>
                <div className="muted text-xs">
                  {ev.actor_user_id != null ? `админ ${ev.actor_user_id}` : "cron / система"}
                </div>
                <EventPayload ev={ev} />
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
