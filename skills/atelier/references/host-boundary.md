# Codex host boundary

Atelier's v0 host adapter is instruction-led. Codex supplies installed-skill
identity and live provider observations; the deterministic helper validates
them. Atelier does not scan for a convenient substitute, copy Agent Scripts, or
perform provider mutations through this boundary.

## Startup preflight

Before native-state inspection or future work delegation:

1. Resolve `agent-scripts:implement-ticket` from the current Codex skill catalog.
   Use the exact installed skill root supplied by Codex. A same-named repository
   skill, source checkout, copied directory, or guessed cache path is not an
   installed identity.
   The helper pins the complete delegated-execution contract bundle, then
   verifies that the dependency's invocation schema supports every v0 authority
   action and terminal state declared by `host-capability.json`.
2. Prove that `github@openai-curated` is installed and callable in the current
   Codex task. Connector installation and GitHub authorization are separate
   prerequisites.
3. Discover read-only host operations for every logical operation named in
   `host-capability.json`. Codex may use an authenticated read-only `gh api`
   query to fill a field the installed connector does not expose, but the
   connector itself remains required. Never substitute a browser scrape, cached
   prose, or a mutation tool.
4. Run the dependency check from this skill directory:

   ```text
   python3 scripts/host_boundary.py check \
     --skill-name agent-scripts:implement-ticket \
     --skill-root <exact-installed-skill-root> \
     --connector github@openai-curated \
     --operation github.issue.read \
     --operation github.issue.relationships.read \
     --operation github.pull-request.read \
     --operation github.pull-request.comments.read \
     --operation github.pull-request.reviews.read \
     --operation github.pull-request.checks.read \
     --operation github.pull-request.threads.read
   ```

5. Capture a UTC `read_started_at` timestamp immediately before the first live
   provider read. Read live GitHub state and normalize it to
   `github-observation.schema.json`. Preserve GitHub node IDs, exact candidate
   SHAs, timestamps, native `parent`, `subIssues`, `blockedBy`, and `blocking`
   relationships, and complete pagination. Mark every completeness field true
   only after the corresponding collection is fully read. Set `observed_at`
   after the last required read completes.
6. Validate the observation:

   ```text
   python3 scripts/host_boundary.py validate-observation \
     <observation.json> \
     --not-before <read_started_at>
   ```

   The descriptor's deterministic freshness fence accepts observations no more
   than five minutes old, permits five seconds of future clock skew, and rejects
   evidence captured before this read boundary.

Delete or retain the temporary observation according to the invoking task's
artifact policy. It is an observation, not shared Atelier state.

## Failure contract

Stop before claim, delegation, mailbox mutation, provider mutation, delivery,
or acceptance when any prerequisite is missing or mismatched. Report the exact
diagnostic emitted by the helper or name the missing connector operation.

In particular, fail closed when:

- the plugin-qualified skill name is unavailable or resolves ambiguously;
- the installed skill, capability manifest, or delegated protocol bundle hash
  differs;
- the dependency-owned manifest validator fails;
- any manifest-referenced schema, contract, or validator is missing;
- the GitHub connector identity or authorization cannot be proven;
- a required read operation is unavailable;
- pagination is incomplete;
- an observation is malformed, stale, or candidate-inconsistent; or
- only a copied workflow or mutation-capable fallback is available.

The boundary proves compatibility and typed read access only. It does not
implement `plan`, `work`, `audit`, mailbox writes, delegation, acceptance, or
any Agent Scripts transitive workflow.
