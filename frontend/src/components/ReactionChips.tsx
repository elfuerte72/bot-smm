import type { ReactionEntry } from "../types";

export default function ReactionChips({
  reactions,
  max,
}: {
  reactions: ReactionEntry[];
  max?: number;
}) {
  if (!reactions.length) return null;
  const shown = max ? reactions.slice(0, max) : reactions;
  const rest = max ? reactions.length - shown.length : 0;
  return (
    <div className="reaction-chips">
      {shown.map((r) => (
        <span key={r.emoji} className="reaction-chip">
          <span>{r.emoji}</span>
          <span className="reaction-chip__count">{r.count}</span>
        </span>
      ))}
      {rest > 0 && <span className="reaction-chip reaction-chip__count">+{rest}</span>}
    </div>
  );
}
