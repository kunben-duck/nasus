export function MetricMini({ label, value, unavailable }: { label: string; value: string; unavailable?: boolean }) {
  return (
    <div className={`metric-mini${unavailable ? ' metric-mini-unavailable' : ''}`}>
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  )
}
