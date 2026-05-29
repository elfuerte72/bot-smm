import type { PostStatus } from "../types";

const STATUS_META: Record<PostStatus, { label: string; color: string }> = {
  draft: { label: "Черновик", color: "var(--c-draft)" },
  publishing: { label: "Публикуется", color: "var(--c-publishing)" },
  published: { label: "Опубликован", color: "var(--c-published)" },
  rejected: { label: "Отклонён", color: "var(--c-rejected)" },
};

export default function StatusBadge({ status }: { status: PostStatus | null }) {
  if (!status) return null;
  const meta = STATUS_META[status];
  return (
    <span
      className="badge"
      style={{
        color: meta.color,
        background: `color-mix(in srgb, ${meta.color} 16%, transparent)`,
      }}
    >
      <span className="badge__dot" />
      {meta.label}
    </span>
  );
}
