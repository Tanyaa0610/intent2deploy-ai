import type { ManagedRepository } from "../types";

export const BUSY_STATUSES = new Set(["cloning", "indexing", "syncing"]);

export function isBusy(repo: ManagedRepository): boolean {
  return BUSY_STATUSES.has(repo.status);
}

export function kindLabel(repo: ManagedRepository): string {
  if (repo.kind === "github") return repo.is_private ? "GitHub · private" : "GitHub";
  return repo.kind === "created" ? "Local · new" : "Local";
}

export function timeAgo(iso: string | null): string {
  if (!iso) return "—";
  // Backend timestamps are naive UTC.
  const t = new Date(iso.endsWith("Z") || iso.includes("+") ? iso : `${iso}Z`).getTime();
  const s = Math.max(0, Math.round((Date.now() - t) / 1000));
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return `${Math.floor(s / 86400)}d ago`;
}

/** One status for the card: operation in progress > error > missing path > index state. */
export function repoStatus(repo: ManagedRepository): { tone: string; label: string } {
  if (repo.status === "cloning") return { tone: "accent", label: "Cloning" };
  if (repo.status === "indexing") return { tone: "accent", label: "Indexing" };
  if (repo.status === "syncing") return { tone: "accent", label: "Pulling" };
  if (repo.status === "error") return { tone: "danger", label: "Error" };
  if (!repo.accessible) return { tone: "danger", label: "Path missing" };
  if (!repo.indexed_at) return { tone: "warn", label: "Not indexed" };
  return { tone: "success", label: "Indexed" };
}

export function indexSummary(repo: ManagedRepository): string {
  if (repo.status === "indexing") return "Indexing…";
  if (!repo.indexed_at) return "Not indexed";
  if (repo.source_file_count === 0) {
    return `No source code · workflows will generate a new project · ${timeAgo(repo.indexed_at)}`;
  }
  return `${repo.file_count} files · ${repo.chunk_count} chunks · ${timeAgo(repo.indexed_at)}`;
}

export function branchSummary(repo: ManagedRepository): string {
  if (!repo.accessible) return "—";
  if (!repo.is_git) return "Not a git repository";
  const head = repo.head ? ` @ ${repo.head}` : " (no commits)";
  return `${repo.branch ?? "?"}${head}${repo.dirty ? " · uncommitted changes" : ""}`;
}
