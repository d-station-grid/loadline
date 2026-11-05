import type { ZoneRow } from "../lib/charts";
import { formatDuration } from "../lib/format";

/** 強度ごとの時間。1 本の帯を強度ごとに塗り分け、下に時間と割合を並べる */
export default function ZoneBreakdown({ rows }: { rows: ZoneRow[] }) {
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
      <ul className="zone-list" aria-label="Time in each zone">
        {rows.map((r) => (
          <li key={r.key}>
            <span className="swatch" style={{ background: r.color }} />
            <span>{r.label}</span>
            <span className="num">{formatDuration(r.sec)}</span>
            <span className="num share">{r.percent}%</span>
          </li>
        ))}
      </ul>
    </>
  );
}
