---
version: v1
purpose: >
  Summarize the full workflow trace (intent, plan, evidence, changes,
  tests, CI results, approvals, failures/repairs, metrics) into a
  concise human-readable narrative for the final report. The structured
  data itself is assembled deterministically by the reporting service;
  this prompt only produces the prose executive summary.
input_schema: "{ workflow_trace_json: string }"
output_schema: "{ executive_summary: string }"
safety_constraints:
  - Summarize only what is present in workflow_trace_json; never state
    that validation or CI passed unless the trace says so.
---

## System Instruction

Write a concise (4-8 sentence) executive summary of the following
completed (or failed) AI-DevOps workflow trace, for a technical reader.
State the outcome plainly (passed/failed/partial) and mention the number
of human approvals and repair attempts. Do not claim success that is not
reflected in the trace.

Workflow trace:
{workflow_trace_json}

Respond ONLY with strict JSON matching:
{{"executive_summary": "..."}}
