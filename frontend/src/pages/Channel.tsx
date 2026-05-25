import { useEffect, useState } from "react";
import { api } from "../api";
import ErrorView from "../components/ErrorView";
import Sparkline from "../components/Sparkline";
import Spinner from "../components/Spinner";
import type { ChannelStats } from "../types";

function formatDate(iso: string): string {
  const d = new Date(iso.includes("T") ? iso : iso.replace(" ", "T") + "Z");
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString("ru-RU", { day: "2-digit", month: "short" });
}

export default function Channel() {
  const [data, setData] = useState<ChannelStats | null>(null);
  const [error, setError] = useState<unknown>(null);

  useEffect(() => {
    api<ChannelStats>("/channel/stats?days=7").then(setData).catch(setError);
  }, []);

  if (error) return <ErrorView error={error} />;
  if (!data) {
    return (
      <div style={{ textAlign: "center", padding: 20 }}>
        <Spinner />
      </div>
    );
  }

  const memberCount = data.member_count;
  const values = data.snapshots.map((s) => s.member_count);

  return (
    <div>
      <h2 style={{ margin: "0 0 16px" }}>{data.title || data.channel_id}</h2>

      <div className="card" style={{ textAlign: "center" }}>
        <div className="muted" style={{ fontSize: 13 }}>
          Подписчики
        </div>
        <div style={{ fontSize: 40, fontWeight: 700, lineHeight: 1.1 }}>
          {memberCount != null ? memberCount.toLocaleString("ru-RU") : "—"}
        </div>
        {data.snapshots.length > 0 && (
          <div className="muted" style={{ fontSize: 12, marginTop: 4 }}>
            точек за {data.days} дней: {data.snapshots.length}
          </div>
        )}
      </div>

      <div className="card">
        <div style={{ marginBottom: 8, fontWeight: 600 }}>Динамика за {data.days} дней</div>
        <Sparkline data={values} width={320} height={70} />
        {data.snapshots.length > 0 && (
          <div
            className="muted"
            style={{ display: "flex", justifyContent: "space-between", fontSize: 12, marginTop: 4 }}
          >
            <span>{formatDate(data.snapshots[0].ts)}</span>
            <span>{formatDate(data.snapshots[data.snapshots.length - 1].ts)}</span>
          </div>
        )}
      </div>
    </div>
  );
}
