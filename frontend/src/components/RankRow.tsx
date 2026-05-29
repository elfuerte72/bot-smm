import { Link } from "react-router-dom";
import type { ReactionRow } from "../types";
import { formatDate } from "../utils/format";
import ReactionChips from "./ReactionChips";

export default function RankRow({
  row,
  rank,
  highlight = true,
}: {
  row: ReactionRow;
  rank: number;
  // highlight=false убирает «медали» 1-2-3 — для анти-топа они вводят в заблуждение.
  highlight?: boolean;
}) {
  const numClass =
    highlight && rank <= 3 ? `rank__num rank__num--${rank}` : "rank__num";

  const inner = (
    <div className="card rank">
      <div className={numClass}>{rank}</div>
      <div className="rank__body">
        <div className="rank__title">{row.title}</div>
        <ReactionChips reactions={row.reactions} max={4} />
      </div>
      <div className="rank__count">
        <div className="rank__count-num">{row.total_count}</div>
        {row.published_at && (
          <div className="muted text-xs" style={{ marginTop: 2 }}>
            {formatDate(row.published_at)}
          </div>
        )}
      </div>
    </div>
  );

  if (row.draft_id != null) {
    return (
      <Link to={`/posts/${row.draft_id}`} className="tappable">
        {inner}
      </Link>
    );
  }
  return inner;
}
