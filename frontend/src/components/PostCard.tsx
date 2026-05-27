import { Link } from "react-router-dom";
import type { Post, PostStatus } from "../types";

const STATUS_LABEL: Record<PostStatus, string> = {
  draft: "draft",
  publishing: "publishing",
  published: "published",
  rejected: "rejected",
};

const STATUS_COLOR: Record<PostStatus, string> = {
  draft: "#5288c1",
  publishing: "#d4a93c",
  published: "#3f9d5f",
  rejected: "#a8504a",
};

function StatusBadge({ status }: { status: PostStatus | null }) {
  if (!status) return null;
  return (
    <span
      style={{
        display: "inline-block",
        padding: "2px 8px",
        borderRadius: 6,
        fontSize: 11,
        fontWeight: 600,
        background: STATUS_COLOR[status],
        color: "#fff",
        textTransform: "uppercase",
      }}
    >
      {STATUS_LABEL[status]}
    </span>
  );
}

function formatDate(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso.includes("T") ? iso : iso.replace(" ", "T") + "Z");
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString("ru-RU", {
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export default function PostCard({ post }: { post: Post }) {
  return (
    <Link
      to={`/posts/${post.id}`}
      className="card"
      style={{ display: "block", textDecoration: "none", color: "inherit" }}
    >
      <div style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 6 }}>
        <StatusBadge status={post.status} />
        <span className="muted" style={{ fontSize: 12 }}>
          {formatDate(post.created_at)}
        </span>
        {post.total_reactions != null && post.total_reactions > 0 && (
          <span className="muted" style={{ fontSize: 12, marginLeft: "auto" }}>
            ♥ {post.total_reactions}
          </span>
        )}
      </div>
      <div style={{ fontWeight: 600, marginBottom: 4 }}>{post.title}</div>
      <div className="muted" style={{ fontSize: 13 }}>
        {post.preview}
      </div>
      <div
        style={{
          marginTop: 6,
          fontSize: 12,
          fontWeight: 500,
          color: "var(--tg-link)",
        }}
      >
        Читать полностью →
      </div>
    </Link>
  );
}
