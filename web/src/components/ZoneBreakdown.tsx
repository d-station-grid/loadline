import type { ZoneRow } from "../lib/charts";
import { useI18n } from "../i18n";
import { formatDuration } from "../lib/format";

/** 強度ごとの時間。1 本の帯を強度ごとに塗り分け、下に時間と割合を並べる */
export default function ZoneBreakdown({ rows }: { rows: ZoneRow[] }) {
  const { m } = useI18n();
  return (
    <>
      <div className="zone-bar" aria-hidden="true">
        {rows.map((r) => (
          <span
            key={r.key}
            style={{ width: `${r.width}%`, background: r.color }}
          />
        ))}
      </div>
      <ul className="zone-list" aria-label={m.charts.timeInZone}>
        {rows.map((r) => (
          <li key={r.key}>
            <span className="swatch" style={{ background: r.color }} />
            <span>{r.label}</span>
            <span className="num">{formatDuration(r.sec, m.duration)}</span>
            <span className="num share">{r.percent}%</span>
          </li>
        ))}
      </ul>
    </>
  );
}
