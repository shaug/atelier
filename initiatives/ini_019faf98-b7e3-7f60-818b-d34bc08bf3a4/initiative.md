---
schema: atelier.initiative/v1
id: ini_019faf98-b7e3-7f60-818b-d34bc08bf3a4
title: Dogfood accountable Atelier coordination
---
## Intent

Prove Atelier can coordinate one accountable project changeset across separate planner, worker, audit, and operator tasks through durable native GitHub state and the canonical Git mailbox.

## Rationale

Issue #781 is the first production dogfood of the v0 planning, claiming, delegation, audit, recovery, and acceptance boundaries implemented by epic #772.

## Non Goals

No behavior changes, automation, provider mutation code, merge, deployment, native issue closure, or post-v0 #782/#783 work.

## Constraints

The Git mailbox is the only shared Atelier state; Agent Scripts owns implementation; distinct tasks preserve authority boundaries; all evidence must be reconstructable without transcript memory.

## Edge Cases

Interruption must recover in a fresh task; stale or unknown evidence must fail closed; delivery, acceptance, merge, deployment, and ticket completion remain distinct.

## Related Context

GitHub issue shaug/atelier#781, epic #772, and the existing planning, claiming, delegation, audit, host-boundary, and mailbox references define the production lifecycle.

## Outcome

One review-sized documentation assignment proceeds through the production lifecycle with durable evidence sufficient for an adversarial reconstruction.
