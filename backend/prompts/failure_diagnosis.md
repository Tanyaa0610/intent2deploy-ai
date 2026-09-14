---
version: v1
purpose: >
  Diagnose why a validation stage failed, using the captured stdout/stderr
  and the relevant retrieved code, without proposing a fix yet.
input_schema: "{ stage: string, stdout: string, stderr: string, retrieved_context: string }"
output_schema: "{ diagnosis: string, likely_root_cause: string, affected_files: string[] }"
safety_constraints:
  - Base the diagnosis only on the provided logs and code; do not
    fabricate stack frames or error messages not present in the logs.
---

## System Instruction

A validation stage failed. Diagnose the likely root cause.

Stage: {stage}

stdout:
{stdout}

stderr:
{stderr}

Relevant retrieved code:
{retrieved_context}

Respond ONLY with strict JSON matching:
{{"diagnosis": "...", "likely_root_cause": "...", "affected_files": ["..."]}}
