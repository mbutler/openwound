/** The twelve passes drawn as rows of cells, one cell per code. */

import type { ReactElement } from "react";

const INKS = ["#4a5a8a", "#8a5a3a", "#5a7a4a", "#a08030", "#6a6a72", "#7a4a7a", "#3a7a7a", "#b09060"];

export function Band({
  levels,
  codes,
  keep,
  changed,
  compact = false,
}: {
  levels: number[];
  codes: number[];
  keep: number;
  changed?: string;
  compact?: boolean;
}) {
  let offset = 0;
  const rows = levels.map((length, index) => {
    const start = offset;
    offset += length;
    return { index, length, start };
  });
  return (
    <div
      className={compact ? "band compact" : "band"}
      role="img"
      aria-label={`Twelve rows of codes. ${keep} ${keep === 1 ? "row is" : "rows are"} kept; the rest are sampled.`}
    >
      {rows.map((row) => {
        const kept = row.index < keep;
        const cells: ReactElement[] = [];
        for (let position = 0; position < row.length; position += 1) {
          const at = row.start + position;
          const code = codes[at] ?? 0;
          const wasChanged = changed ? changed[at] === "1" : false;
          const tier = (code >> 3) % 4;
          const opacity = kept ? 0.55 + 0.45 * (tier / 3) : wasChanged ? 0.9 : 0.18;
          cells.push(
            <i key={position} style={{ background: wasChanged && !kept ? "#2f5d73" : INKS[code % 8], opacity }} />,
          );
        }
        return (
          <div key={row.index}>
            <div className="band-row">
              <span className="n">{row.index + 1}</span>
              <div className="cells">{cells}</div>
              <span className="len">
                {row.length} {row.length === 1 ? "code" : "codes"}
              </span>
            </div>
            {!compact && keep > 0 && row.index + 1 === keep && (
              <div className="keep-line" aria-hidden="true">
                <span />
                <div>
                  <span>kept above · sampled below</span>
                </div>
                <span />
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
