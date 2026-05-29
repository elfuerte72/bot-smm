import type { CSSProperties } from "react";

export function Skeleton({
  width,
  height = 12,
  radius = 6,
  style,
}: {
  width?: number | string;
  height?: number | string;
  radius?: number;
  style?: CSSProperties;
}) {
  return (
    <span
      className="skeleton"
      style={{ display: "block", width: width ?? "100%", height, borderRadius: radius, ...style }}
      aria-hidden
    />
  );
}

// Скелетон карточки поста — повторяет геометрию PostCard, чтобы при загрузке
// не было «прыжка» layout.
export function PostCardSkeleton() {
  return (
    <div className="card" aria-hidden>
      <div style={{ display: "flex", gap: 8, marginBottom: 12 }}>
        <Skeleton width={64} height={16} radius={999} />
        <Skeleton width={70} height={12} />
      </div>
      <Skeleton width="80%" height={15} style={{ marginBottom: 10 }} />
      <Skeleton width="100%" height={12} style={{ marginBottom: 6 }} />
      <Skeleton width="55%" height={12} />
    </div>
  );
}

export function PostListSkeleton({ count = 5 }: { count?: number }) {
  return (
    <div className="stack" aria-busy>
      {Array.from({ length: count }, (_, i) => (
        <PostCardSkeleton key={i} />
      ))}
    </div>
  );
}
