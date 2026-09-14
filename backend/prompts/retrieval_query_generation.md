---
version: v1
purpose: >
  Expand a developer intent into a small set of focused retrieval queries
  (semantic + keyword) that will be run against the repository index, so
  retrieval is not limited to the literal intent string.
input_schema: "{ intent: string, normalized_requirement: string }"
output_schema: "{ queries: string[] }"
safety_constraints:
  - Queries must stay within the scope of the stated requirement.
---

## System Instruction

Given the developer intent:

"{intent}"

and normalized requirement:

"{normalized_requirement}"

Produce 3-6 short search queries that would help locate the relevant
files, functions, tests, and configuration in the repository. Vary the
phrasing (e.g. one about the feature itself, one about existing related
functionality, one about tests, one about configuration/dependencies).

Respond ONLY with strict JSON matching:
{{"queries": ["...", "..."]}}
