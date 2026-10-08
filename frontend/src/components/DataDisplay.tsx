import type { ReactNode } from "react";

export function Tbl({ headers, rows }: { headers: string[]; rows: (string | number | ReactNode)[][] }) {
  if (rows.length === 0) {
    return <p style={{ fontSize: 13, color: "var(--text-faint)" }}>Not recorded.</p>;
  }
  return (
    <div style={{ overflowX: "auto" }}>
      <table>
        <thead>
          <tr>{headers.map((h) => <th key={h}>{h}</th>)}</tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr key={i}>
              {row.map((cell, j) => <td key={j} style={{ fontSize: 12.5 }}>{cell === "" || cell === null || cell === undefined ? "—" : cell}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function Expand({ title, defaultOpen, children }: { title: string; defaultOpen?: boolean; children: ReactNode }) {
  return (
    <details style={{ marginTop: 14 }} open={defaultOpen}>
      <summary style={{ cursor: "pointer", fontWeight: 700, fontSize: 13.5, padding: "4px 0" }}>{title}</summary>
      <div style={{ marginTop: 8 }}>{children}</div>
    </details>
  );
}
