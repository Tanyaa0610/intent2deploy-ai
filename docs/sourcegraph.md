# Sourcegraph OSS and Semantic Code Navigation

The course's first phase specifically assesses Sourcegraph setup and
semantic code navigation. This document explains how Sourcegraph OSS
relates to this project, and is explicit about what is and is not
implemented, per the master spec's instruction not to falsely claim the
application itself is powered by Sourcegraph.

## What this project implements itself

Intent2Deploy AI has its own working semantic retrieval layer
(LangChain + ChromaDB — see `docs/rag.md`), which is what the
application's Repository Intelligence tab and Q&A feature actually run
on. This is intentionally a from-scratch, explainable RAG pipeline built
for this course's RAG/prompt-engineering learning outcomes, not a
wrapper around an external navigation tool.

## How Sourcegraph OSS would complement it

Sourcegraph provides precise, LSIF/SCIP-based code navigation (go-to-
definition, find-references, symbol search) across a codebase, which is
a different technique from embedding-based semantic retrieval:

| | This project's RAG | Sourcegraph |
|---|---|---|
| Basis | Embeddings + BM25 + path/symbol heuristics | Static analysis / language servers (precise) |
| Answers | "What code is semantically relevant to this intent?" | "Where exactly is this symbol defined/used?" |
| Precision | Approximate, ranked | Exact |
| Setup | None (pure Python, offline) | Requires running Sourcegraph OSS (Docker) and indexing |

They are complementary: Sourcegraph is excellent for "find all call
sites of `AuthService.login`"; this project's retrieval is designed for
"find the code relevant to a natural-language intent," which Sourcegraph
does not do natively.

## Setting up Sourcegraph OSS against the demo repository (student exercise)

```bash
docker run -d --name sourcegraph \
  -p 7080:7080 -p 3370:3370 \
  --volume ~/.sourcegraph/config:/etc/sourcegraph \
  --volume ~/.sourcegraph/data:/var/opt/sourcegraph \
  sourcegraph/server:latest
```

Then add `demo-repository/` as a local repository via the Sourcegraph
admin UI (Site Admin → Manage repositories → Add a local repository).

### Example queries to run in Sourcegraph, once configured

- `repo:demo-repository AuthService` — find the class definition.
- `repo:demo-repository type:symbol validate_token` — jump to the symbol.
- `repo:demo-repository "get_order_total"` — find every reference to the
  buggy function used in the bug-fix benchmark task.

### Evidence placeholders for the student to capture

- [ ] Screenshot: Sourcegraph search results for `AuthService`.
- [ ] Screenshot: go-to-definition from a call site of `validate_token`.
- [ ] Screenshot: find-references for `get_order_total`.

## Repository-intelligence adapter seam

If a practical Sourcegraph OSS integration becomes available (e.g. the
grading environment has it running), it would plug in as an additional
retrieval source alongside `app/services/rag/retriever.py`'s existing
signals — the `RetrievalResult` dataclass already carries a
`retrieval_method` field designed to be extended with a `"sourcegraph"`
value. No such integration is implemented in this build; this section
documents the seam rather than fabricating one.
