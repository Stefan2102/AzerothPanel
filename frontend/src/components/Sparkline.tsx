export function Sparkline({ values, max, color = "var(--accent)", height = 28 }: { values: number[]; max?: number; color?: string; height?: number }) {
  if (values.length < 2) return <div style={{ height }} />;
  const top = Math.max(max ?? 0, ...values, 1);
  const step = 100 / (values.length - 1);
  const pts = values.map((v, i) => `${(i * step).toFixed(2)},${(height - (v / top) * (height - 2) - 1).toFixed(2)}`).join(" ");
  return (
    <svg viewBox={`0 0 100 ${height}`} preserveAspectRatio="none" width="100%" height={height} aria-hidden>
      <polyline points={`0,${height} ${pts} 100,${height}`} fill={color} fillOpacity={0.12} stroke="none" />
      <polyline points={pts} fill="none" stroke={color} strokeWidth={1.5} vectorEffect="non-scaling-stroke" />
    </svg>
  );
}
