interface SparklineProps {
  data: number[];
  width?: number;
  height?: number;
  strokeWidth?: number;
}

export default function Sparkline({
  data,
  width = 320,
  height = 60,
  strokeWidth = 2,
}: SparklineProps) {
  if (data.length < 2) {
    return (
      <svg width={width} height={height} role="img" aria-label="sparkline empty">
        <text
          x="50%"
          y="50%"
          textAnchor="middle"
          dominantBaseline="middle"
          fill="var(--tg-hint)"
          fontSize="12"
        >
          мало точек для графика
        </text>
      </svg>
    );
  }

  const min = Math.min(...data);
  const max = Math.max(...data);
  const range = max - min || 1;
  const stepX = width / (data.length - 1);

  const points = data
    .map((value, idx) => {
      const x = idx * stepX;
      const y = height - ((value - min) / range) * height;
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");

  const areaPoints = `0,${height} ${points} ${width.toFixed(1)},${height}`;

  return (
    <svg
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      role="img"
      aria-label={`sparkline min=${min} max=${max}`}
    >
      <polyline
        points={areaPoints}
        fill="var(--tg-button)"
        fillOpacity="0.18"
        stroke="none"
      />
      <polyline
        points={points}
        fill="none"
        stroke="var(--tg-button)"
        strokeWidth={strokeWidth}
        strokeLinejoin="round"
        strokeLinecap="round"
      />
    </svg>
  );
}
