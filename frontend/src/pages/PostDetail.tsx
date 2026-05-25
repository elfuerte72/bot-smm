import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api";
import ErrorView from "../components/ErrorView";
import Spinner from "../components/Spinner";
import type { DraftEvent, PostDetailResponse } from "../types";

function formatDateTime(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso.includes("T") ? iso : iso.replace(" ", "T") + "Z");
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString("ru-RU");
}

function EventCard({ ev }: { ev: DraftEvent }) {
  return (
    <div className="card">
      <div style={{ display: "flex", justifyContent: "space-between", gap: 8, marginBottom: 6 }}>
        <strong>{eventLabel(ev.event_type)}</strong>
        <span className="muted" style={{ fontSize: 12 }}>
          {formatDateTime(ev.created_at)}
        </span>
      </div>
      {ev.actor_user_id != null ? (
        <div className="muted" style={{ fontSize: 12, marginBottom: 6 }}>
          actor: <code>{ev.actor_user_id}</code>
        </div>
      ) : (
        <div className="muted" style={{ fontSize: 12, marginBottom: 6 }}>
          cron / system
        </div>
      )}
      <EventPayload ev={ev} />
    </div>
  );
}

function eventLabel(type: DraftEvent["event_type"]): string {
  switch (type) {
    case "created":
      return "Создан";
    case "edited":
      return "Отредактирован";
    case "regenerated_from":
      return "Перегенерирован";
    case "approved":
      return "Одобрен";
    case "rejected":
      return "Отклонён";
  }
}

function EventPayload({ ev }: { ev: DraftEvent }) {
  const p = ev.payload;
  if (ev.event_type === "edited" && typeof p.diff_unified === "string") {
    return <DiffBlock diff={p.diff_unified} />;
  }
  if (ev.event_type === "created") {
    return (
      <div style={{ fontSize: 13 }}>
        <div>mode: <code>{String(p.mode ?? "—")}</code></div>
        {typeof p.topic === "string" && <div>topic: {p.topic}</div>}
        {typeof p.source_url === "string" && (
          <div className="muted" style={{ wordBreak: "break-all" }}>
            {p.source_url}
          </div>
        )}
        {typeof p.title === "string" && <div>title: {p.title}</div>}
      </div>
    );
  }
  if (ev.event_type === "regenerated_from" && typeof p.new_draft_id === "number") {
    return (
      <div style={{ fontSize: 13 }}>
        <Link to={`/posts/${p.new_draft_id}`}>
          → новый драфт #{p.new_draft_id}
          {typeof p.new_title === "string" ? `: ${p.new_title}` : ""}
        </Link>
      </div>
    );
  }
  if (ev.event_type === "approved") {
    return (
      <div style={{ fontSize: 13 }} className="muted">
        {typeof p.channel_id === "string" && <div>channel: {p.channel_id}</div>}
        {typeof p.tg_message_id === "number" && <div>tg_message_id: {p.tg_message_id}</div>}
      </div>
    );
  }
  if (ev.event_type === "rejected" && typeof p.reason === "string") {
    return (
      <div className="muted" style={{ fontSize: 13 }}>
        reason: {p.reason}
      </div>
    );
  }
  return null;
}

function DiffBlock({ diff }: { diff: string }) {
  const lines = diff.split("\n");
  return (
    <pre
      style={{
        background: "rgba(0,0,0,0.25)",
        padding: 10,
        borderRadius: 8,
        margin: 0,
        fontSize: 12,
        whiteSpace: "pre-wrap",
        wordBreak: "break-word",
        overflowX: "auto",
      }}
    >
      {lines.map((line, i) => {
        let color: string | undefined;
        if (line.startsWith("+") && !line.startsWith("+++")) color = "#5ec27a";
        else if (line.startsWith("-") && !line.startsWith("---")) color = "#e07a7a";
        else if (line.startsWith("@@")) color = "#6ab3f3";
        return (
          <span key={i} style={{ color, display: "block" }}>
            {line || "​"}
          </span>
        );
      })}
    </pre>
  );
}

export default function PostDetail() {
  const { id } = useParams<{ id: string }>();
  const [data, setData] = useState<PostDetailResponse | null>(null);
  const [error, setError] = useState<unknown>(null);

  useEffect(() => {
    if (!id) return;
    setData(null);
    setError(null);
    api<PostDetailResponse>(`/posts/${encodeURIComponent(id)}`)
      .then(setData)
      .catch(setError);
  }, [id]);

  if (error) return <ErrorView error={error} />;
  if (!data) {
    return (
      <div style={{ textAlign: "center", padding: 20 }}>
        <Spinner />
      </div>
    );
  }

  const { post, events, reactions } = data;
  return (
    <div>
      <div style={{ marginBottom: 12 }}>
        <Link to="/" className="muted">
          ← Назад к постам
        </Link>
      </div>

      <h2 style={{ margin: "0 0 8px" }}>{post.title}</h2>
      <div className="muted" style={{ fontSize: 13, marginBottom: 12 }}>
        <span>#{post.id}</span> • <span>{post.status ?? "—"}</span> •{" "}
        <span>{formatDateTime(post.created_at)}</span>
      </div>

      {post.primary_source_url && (
        <div className="card" style={{ fontSize: 13 }}>
          <span className="muted">Источник: </span>
          <a href={post.primary_source_url} target="_blank" rel="noreferrer">
            {post.primary_source_url}
          </a>
        </div>
      )}

      <div
        className="card"
        style={{ whiteSpace: "pre-wrap", lineHeight: 1.5, fontSize: 14 }}
        // formatted_text — HTML-payload, который шлётся в Telegram (<b>, <a>,
        // <code>, <blockquote>). Источник — наш SYSTEM_PROMPT, прошедший
        // антибот-фильтры и валидацию длины. Внутренний инструмент,
        // dangerouslySetInnerHTML здесь допустим.
        dangerouslySetInnerHTML={{
          __html: post.formatted_text || post.preview || "(пусто)",
        }}
      />

      {reactions && reactions.reactions.length > 0 && (
        <div className="card">
          <div style={{ marginBottom: 6, fontWeight: 600 }}>
            Реакции: {reactions.total_count}
          </div>
          <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
            {reactions.reactions.map((r) => (
              <span key={r.emoji} style={{ fontSize: 14 }}>
                <span style={{ fontSize: 18 }}>{r.emoji}</span>{" "}
                <span className="muted">×{r.count}</span>
              </span>
            ))}
          </div>
          {reactions.updated_at && (
            <div className="muted" style={{ fontSize: 12, marginTop: 6 }}>
              обновлено {formatDateTime(reactions.updated_at)}
            </div>
          )}
        </div>
      )}

      <h3 style={{ marginTop: 20, marginBottom: 10 }}>История</h3>
      {events.length === 0 ? (
        <div className="card muted">Событий нет.</div>
      ) : (
        events.map((ev) => <EventCard key={ev.id} ev={ev} />)
      )}
    </div>
  );
}
