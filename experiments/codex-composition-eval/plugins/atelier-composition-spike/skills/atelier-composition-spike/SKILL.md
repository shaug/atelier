---
name: atelier-composition-spike
description: Run the disposable host-native composition evaluation when validating that Atelier can coordinate fresh Codex workers through a separately installed Agent Scripts implement-ticket skill, durable delegated-authority checkpoints, and a versioned terminal contract without containing the implementation workflow.
---

# Atelier Composition Spike

Prove the host-native dependency boundary before an Atelier reset. Keep this
skill evaluation-only: do not mutate GitHub, production systems, legacy Atelier
state, or real project tickets.

## Preconditions

Require all of the following:

- a fresh Codex process can resolve `$implement-ticket` from the independently
  installed Agent Scripts plugin cache by stable name;
- the evaluation workspace contains a separately installed, commit-pinned copy
  of `implement-ticket` at `.agents/skills/implement-ticket` only for capability
  validation by the coordinator;
- an exact Codex package is copied into the evaluation provenance root and its
  executable runs successfully; and
- the output directory is disposable and does not already exist.

Stop if the plugin skill is unavailable or if Codex resolves a source checkout,
a copied workflow, or the evaluator's validation copy instead of the plugin
cache.

## Run the evaluation

Resolve `scripts/run_composition.py`, `scripts/launch_worker.py`, and
`scripts/launch_reviewer.py` from this installed skill. Use one new evaluation
root containing `success/`, `denied/`, `evidence/`, and `provenance/` children.

1. Prepare the two cases. Preparation may create only the fixture repository,
   bare remote, invocation, policy state, and fixture metadata.

   ```text
   python3 <skill>/scripts/run_composition.py prepare \
     --workspace <workspace> --output <root>/success --case success
   python3 <skill>/scripts/run_composition.py prepare \
     --workspace <workspace> --output <root>/denied --case denied
   ```

1. Launch one fresh ephemeral Codex worker per case from the same preserved
   executable. The outer launcher is also a one-shot supervisor: it services
   exactly one worker-authored, hash-bound review request by starting a fresh
   read-only reviewer outside the worker sandbox. Each worker receives the same
   provider-adapter task, explicitly invokes `$implement-ticket`, and is not
   told which case is expected to allow or deny the PR transition.

   ```text
   python3 <skill>/scripts/launch_worker.py \
     --case-root <root>/success \
     --transport <skill>/scripts/run_composition.py \
     --codex-executable <root>/provenance/codex/bin/codex
   python3 <skill>/scripts/launch_worker.py \
     --case-root <root>/denied \
     --transport <skill>/scripts/run_composition.py \
     --codex-executable <root>/provenance/codex/bin/codex
   ```

1. Verify independently after both workers terminate.

   ```text
   python3 <skill>/scripts/run_composition.py verify \
     --workspace <workspace> \
     --success <root>/success \
     --denied <root>/denied \
     --output <root>/evidence
   ```

1. Inspect both raw worker `codex-events.jsonl` transcripts, raw isolated-review
   `review-events.jsonl` transcripts, review request/completion pairs, host
   launch records, worker artifacts, checkpoint ledgers, remote refs, package
   provenance, and `evidence/checks.json`. Treat missing or malformed raw
   evidence as failure. Do not repair a failed worker or reviewer artifact in
   place.

## Evidence boundary

A passing fixture must show that:

- fresh Codex workers invoked the plugin-cached `implement-ticket` skill;
- the workers, not Atelier's scripts, created and published candidates, authored
  checkpoint requests, handled a PR allowance and denial, wrote terminal
  results, and created the allowed PR fixture marker;
- the coordinator durably fenced every request to one invocation, ticket
  observation, repository, authority allowance, sequence, and token;
- candidate acknowledgement followed an independent exact-ref lookup;
- an isolated, fresh, read-only Codex process reviewed each exact candidate and
  preserved its input, launch record, raw transcript, and structured output;
- foreign invocation, malformed capability, pre-mutation excess authority,
  excess terminal authority, and mismatched acknowledgement checks fail closed;
  and
- Atelier contains transport, policy, and verification logic but no copied Agent
  Scripts implementation workflow.

The bare remote and PR marker are provider fixtures. Do not claim that this run
validates live GitHub, production Atelier, malicious-worker isolation, or Claude
Code host compatibility.

## Output

Return the JSON object written to `evidence/summary.json`, including capability
and skill hashes, scenario counts, failures, the evidence path, and a plain
boundary observation. Preserve the evidence root for adversarial review.
