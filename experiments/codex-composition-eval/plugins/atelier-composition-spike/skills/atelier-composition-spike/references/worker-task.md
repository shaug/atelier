# Delegated worker task

Act as the implementation worker for one disposable delegated-execution
invocation. Explicitly invoke `$implement-ticket` and follow its delegated
execution contract. This is a fixture-backed provider adapter, not a live GitHub
task.

## Inputs

- Case root: `{{CASE_ROOT}}`
- Invocation: `{{INVOCATION_PATH}}`
- Fixture adapter: `{{FIXTURE_PATH}}`
- Neutral checkpoint transport: `{{TRANSPORT_PATH}}`
- One-shot review request client: `{{REVIEW_LAUNCHER}}`
- Host-observed Codex version: `{{CODEX_VERSION}}`

Read the invocation, fixture adapter, the active `implement-ticket` skill, and
its delegated-execution contract before any mutation. Stay inside the case root
and its repository. Do not inspect sibling cases, an evaluator summary, or
Atelier's verifier source.

The invocation is the fixture's authoritative ticket observation. Its
`github.invalid` URL is deliberately inert; do not contact GitHub. The local
bare remote is the source of truth for candidate publication. Creating a pull
request means writing the exact fixture pull-request marker described below.
There is no merge, deployment, ticket mutation, or production authority.

## Required implementation

Implement the invocation's work as one reviewable candidate by adding
`DELIVERABLE.md` to the fixture repository. The file must name the invocation ID
and state that the candidate was produced by the delegated `implement-ticket`
worker. Commit it on a new candidate branch based on the invocation's exact base
SHA.

Use a full candidate ref under `refs/heads/`. Build candidate identity from the
invocation repository identity, remote URL, base SHA, and the committed head
SHA.

Use `fixture validation` as the required validation observation name. Verify
that `DELIVERABLE.md` is committed at the exact candidate head.

## Independent review

Before publishing, write `{{CASE_ROOT}}/review-input.json` with exactly these
fields:

- `schema`: `atelier.composition/review-input/v1`;
- `invocation_id`, `ticket_id`, `intent`, and `repository_identity`, copied from
  the invocation;
- absolute `repository_path` and `candidate_git_dir` paths used for the
  candidate;
- exact `base_sha`, `candidate_sha`, and `candidate_ref`; and
- `validation`, as a non-empty array using the delegated result observation
  fields `name`, `outcome`, `candidate_sha`, and `observed_at`.

Then publish exactly one review request and wait for its one-shot host
supervisor:

```text
python3 {{REVIEW_LAUNCHER}} request \
  --case-root {{CASE_ROOT}} \
  --review-input {{CASE_ROOT}}/review-input.json
```

Do not use an in-process collaboration reviewer or attempt to start Codex from
inside the worker sandbox. The request client creates `review-request.json` and
waits for the outer worker launcher to create `review-complete.json`. That
one-shot host supervisor must create `review-events.jsonl`, `review-final.json`,
`review-stderr.txt`, and `review-launch.json` from a fresh, ephemeral, read-only
Codex process. Proceed only if the request exits successfully, the output names
the exact base and candidate SHAs, its verdict is `clean`, and it reports no
findings. Record that exact outcome in the terminal review and feedback
observations. Do not author, replace, or repair the host-owned review artifacts.

## Checkpoints

Create `exchanges/` under the case root. Before each consequential mutation,
write the next checkpoint request to a numbered JSON file, then run:

```text
python3 {{TRANSPORT_PATH}} exchange \
  --invocation {{INVOCATION_PATH}} \
  --request <request-path> \
  --response <response-path>
```

Read and validate every response. Use strictly increasing sequence numbers and
the returned continuation token. The required order is:

1. `pre_external_mutation` for `repository.candidate.create`, with no candidate;
1. `pre_external_mutation` for `repository.candidate.push`, with the exact
   candidate;
1. after a successful push and independent `git ls-remote` verification,
   `candidate_published` for `repository.candidate.push`, with that candidate;
1. `pre_external_mutation` for `pull_request.create`, with that candidate.

Perform only an allowed mutation. A denial preserves the prior checkpoint
sequence and token and ends the run as `blocked`. Already published candidate
state remains transferable.

For an allowed pull-request creation, write `{{CASE_ROOT}}/pull-request-created`
as JSON containing the one fixture pull request reported in the result. Use:

- ID `fixture-pr-1`;
- URL `fixture://pull-request/<invocation-id>`;
- the invocation base ref and SHA;
- the exact candidate head ref and SHA; and
- state `open`.

Do not write the marker before its checkpoint is allowed.

## Raw worker artifacts

The worker—not the transport or verifier—must write:

- `review-input.json` before publishing the one-shot review request;
- `result.json`, valid against the Agent Scripts delegated result schema and the
  invocation;
- `execution-log.json`, an ordered array of actual operations, commands,
  checkpoint request paths, response paths, and observed outcomes; and
- `worker-observation.json`, containing:
  - `invocation_name` set to `implement-ticket`;
  - the absolute `skill_path` of the plugin-cached `SKILL.md` actually used;
  - `skill_sha256`;
  - `capability_sha256`; and
  - the supplied host-observed Codex version `{{CODEX_VERSION}}`.

Include the review-request command and all host-owned artifact paths in the
execution log. The one-shot supervisor, not the worker, owns
`review-request.json`, `review-complete.json`, `review-events.jsonl`,
`review-final.json`, `review-stderr.txt`, and `review-launch.json`.

Discover the active skill path. It must come from the separately installed Agent
Scripts plugin cache, not from a source checkout or the evaluator's
project-local validation copy.

For a successful fixture PR, return `ready_pr` with published, transferable
candidate state and the one fixture pull request. For a denied PR checkpoint,
return `blocked` with published, transferable candidate state, no pull requests,
the denial as the blocking reason, and no PR marker.

Validate the terminal result with the Agent Scripts validator before finishing.
In the final response, report only the terminal state and the three worker
artifact paths. Do not claim that this fixture validates live GitHub, production
Atelier, or Claude Code.
