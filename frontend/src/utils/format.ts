// SQLite отдаёт время без таймзоны ("2026-05-29 10:00:00") — трактуем как UTC.
function parse(iso: string | null): Date | null {
  if (!iso) return null;
  const d = new Date(iso.includes("T") ? iso : iso.replace(" ", "T") + "Z");
  return Number.isNaN(d.getTime()) ? null : d;
}

export function formatDateTime(iso: string | null): string {
  const d = parse(iso);
  if (!d) return iso ?? "—";
  return d.toLocaleString("ru-RU", {
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function formatDate(iso: string | null): string {
  const d = parse(iso);
  if (!d) return iso ?? "—";
  return d.toLocaleDateString("ru-RU", { day: "2-digit", month: "short" });
}

// "5 минут назад" / "3 ч назад" / "вчера" — компактно для лент.
export function formatRelative(iso: string | null): string {
  const d = parse(iso);
  if (!d) return "—";
  const diff = Date.now() - d.getTime();
  const min = Math.round(diff / 60000);
  if (min < 1) return "только что";
  if (min < 60) return `${min} мин назад`;
  const hours = Math.round(min / 60);
  if (hours < 24) return `${hours} ч назад`;
  const days = Math.round(hours / 24);
  if (days === 1) return "вчера";
  if (days < 7) return `${days} дн назад`;
  return formatDate(iso);
}

export function formatNumber(n: number): string {
  return n.toLocaleString("ru-RU");
}
