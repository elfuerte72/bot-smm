import type { ReactNode } from "react";
import { IconInbox } from "./icons";

export default function EmptyState({
  title,
  subtitle,
  icon,
}: {
  title: string;
  subtitle?: string;
  icon?: ReactNode;
}) {
  return (
    <div className="empty">
      <div className="empty__icon">{icon ?? <IconInbox />}</div>
      <div className="empty__title">{title}</div>
      {subtitle && <div className="text-sm">{subtitle}</div>}
    </div>
  );
}
