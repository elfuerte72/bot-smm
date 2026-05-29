import { useEffect, useId, useRef, useState } from "react";

interface SparklineProps {
  data: number[];
  height?: number;
  // Доля высоты под линию: 0.78 оставляет воздух сверху/снизу.
  fillArea?: number;
  showDot?: boolean;
  strokeWidth?: number;
}

// Адаптивный area-chart. Меряем реальную ширину контейнера (ResizeObserver)
// и рисуем в пиксельных координатах — поэтому маркер на последней точке
// остаётся круглым, а линия не искажается (в отличие от preserveAspectRatio
// "none", который растягивает viewBox неравномерно).
export default function Sparkline({
  data,
  height = 64,
  fillArea = 0.78,
  showDot = true,
  strokeWidth = 2,
}: SparklineProps) {
  const gid = useId().replace(/:/g, "");
  const ref = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(0);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    setWidth(el.clientWidth);
    const ro = new ResizeObserver((entries) => {
      const w = entries[0]?.contentRect.width;
      if (w) setWidth(w);
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  if (data.length < 2) {
    return (
      <div
        className="muted text-xs"
        style={{ height, display: "grid", placeItems: "center" }}
      >
        Мало точек для графика
      </div>
    );
  }

  const W = width;
  const H = height;
  const padX = showDot ? 5 : 0;
  const min = Math.min(...data);
  const max = Math.max(...data);
  const range = max - min || 1;
  const padY = (H * (1 - fillArea)) / 2;
  const usableH = H - padY * 2;
  const usableW = Math.max(0, W - padX * 2);
  const stepX = usableW / (data.length - 1);

  const pts = data.map((v, i) => {
    const x = padX + i * stepX;
    const y = padY + (1 - (v - min) / range) * usableH;
    return [x, y] as const;
  });

  const line = pts.map(([x, y]) => `${x.toFixed(2)},${y.toFixed(2)}`).join(" ");
  const area = `${padX},${H} ${line} ${W - padX},${H}`;
  const last = pts[pts.length - 1];

  return (
    <div ref={ref} style={{ width: "100%", height }}>
      {W > 0 && (
        <svg
          width={W}
          height={H}
          viewBox={`0 0 ${W} ${H}`}
          role="img"
          aria-label={`График: от ${min} до ${max}`}
          style={{ display: "block", overflow: "visible" }}
        >
          <defs>
            <linearGradient id={`grad-${gid}`} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="var(--accent)" stopOpacity="0.32" />
              <stop offset="100%" stopColor="var(--accent)" stopOpacity="0" />
            </linearGradient>
          </defs>
          <polygon points={area} fill={`url(#grad-${gid})`} stroke="none" />
          <polyline
            points={line}
            fill="none"
            stroke="var(--accent)"
            strokeWidth={strokeWidth}
            strokeLinejoin="round"
            strokeLinecap="round"
          />
          {showDot && (
            <g>
              <circle cx={last[0]} cy={last[1]} r="5.5" fill="var(--accent)" opacity="0.2" />
              <circle
                cx={last[0]}
                cy={last[1]}
                r="3"
                fill="var(--accent)"
                stroke="var(--bg)"
                strokeWidth="1.6"
              />
            </g>
          )}
        </svg>
      )}
    </div>
  );
}
