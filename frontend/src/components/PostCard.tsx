import { Link } from "react-router-dom";
import type { Post } from "../types";
import { formatRelative } from "../utils/format";
import { IconChevronRight, IconHeart } from "./icons";
import StatusBadge from "./StatusBadge";

export default function PostCard({ post }: { post: Post }) {
  return (
    <Link to={`/posts/${post.id}`} className="card tappable">
      <div className="post-card__top">
        <StatusBadge status={post.status} />
        <span className="post-card__date">{formatRelative(post.created_at)}</span>
        {post.total_reactions != null && post.total_reactions > 0 && (
          <span className="post-card__reactions">
            <IconHeart size={13} />
            {post.total_reactions}
          </span>
        )}
      </div>
      <div className="post-card__title">{post.title}</div>
      {post.preview && <div className="post-card__preview">{post.preview}</div>}
      <div className="post-card__cta">
        Открыть
        <IconChevronRight />
      </div>
    </Link>
  );
}
