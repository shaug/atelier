---
schema: atelier.project/v1
id: prj_019faf81-a727-7f87-b3bf-ee92b37450eb
name: Atelier
repository: github:shaug/atelier
policy:
  repository: github:shaug/atelier
  path: .atelier/policy.yaml
native_ticket:
  provider: github
  required_before_claim: true
status: active
---

Atelier is the first live v0 dogfood project. Its canonical Git mailbox records
approved intent, fenced worker execution, delivery evidence, and explicit
operator acceptance separately from native GitHub state.
