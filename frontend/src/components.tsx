import { statusLabel } from "./api";

export function StatusBadge({ status }: { status: string }) {
  return (
    <span className={`badge badge-${status}`} data-testid="status">
      {statusLabel(status)}
    </span>
  );
}

export function Score({ value }: { value: number }) {
  return (
    <span className={`score score-${value >= 3 ? "ok" : "low"}`}>
      {value}/5
    </span>
  );
}
