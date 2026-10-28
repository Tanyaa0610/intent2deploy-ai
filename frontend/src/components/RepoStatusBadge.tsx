import type { ManagedRepository } from "../types";
import { isBusy, repoStatus } from "../services/repoMeta";

export function RepoStatusBadge({ repo }: { repo: ManagedRepository }) {
  const { tone, label } = repoStatus(repo);
  return (
    <span className={`status ${tone}${isBusy(repo) ? " pulsing" : ""}`}>
      <span className="dot" />
      {label}
    </span>
  );
}
