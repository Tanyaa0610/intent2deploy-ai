---
version: v1
purpose: >
  Given a failure diagnosis, propose a bounded repair patch. Used inside
  the repair loop, which is capped at MAX_REPAIR_ATTEMPTS (default 2) and
  always requires human approval before being applied.
input_schema: "{ diagnosis: string, root_cause: string, retrieved_context: string }"
output_schema: "{ diagnosis, root_cause, repair_patch, confidence, files[] }"
safety_constraints:
  - The repair patch must be minimal and scoped to the diagnosed root
    cause; do not perform unrelated refactors.
  - Never widen the change beyond the files already touched by the
    original proposed change unless the root cause clearly requires it.
---

## System Instruction

Given the following failure diagnosis, propose a minimal repair patch.

Diagnosis: {diagnosis}
Root cause: {root_cause}

Relevant retrieved code:
{retrieved_context}

Respond ONLY with strict JSON matching:
{{"diagnosis": "...", "root_cause": "...", "repair_patch": "<unified diff>",
  "confidence": 0.0, "files": ["..."]}}
