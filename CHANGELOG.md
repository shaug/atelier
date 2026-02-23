# Changelog

## [0.7.0](https://github.com/shaug/atelier/compare/v0.6.0...v0.7.0) (2026-02-22)

### Overview

This release is the pivot from workspace-only tooling to full planning/runtime
orchestration. Atelier adds planner/worker/session isolation, bead-native epic
and changeset workflows, and mail/queue-driven coordination so multi-agent work
can be run with explicit lifecycle state. It also deepens PR-aware publishing
with strategy gating, review feedback handling, external ticket integration, and
heavy reliability hardening around reconcile/finalization flows.

### Features

- add on-demand planner startup overview refresh
  ([f0405ef](https://github.com/shaug/atelier/commit/f0405efcc0ad269a88b74baf880d1e1916971687))
- **agent-home:** isolate planner and worker sessions
  ([c333506](https://github.com/shaug/atelier/commit/c333506e3550b2831f2dd64a52250208d4f077eb))
- **agent:** add agent home directories
  ([1f79f38](https://github.com/shaug/atelier/commit/1f79f38060e4dac329ee42fb100d797db8b132b1))
- **agent:** add identity config and bead helpers
  ([250e889](https://github.com/shaug/atelier/commit/250e889aff04274dca0dbe8f9eae5ab2198bab85))
- **agent:** inject bd prime addendum into generated AGENTS.md
  ([34c353f](https://github.com/shaug/atelier/commit/34c353f06a81573d85d263d70826188ced68052f))
- **agents:** inject identity env vars
  ([f450338](https://github.com/shaug/atelier/commit/f4503385ed75d58f0b657719c2b86e28292e498f))
- **agents:** scope identity env vars
  ([cc4840f](https://github.com/shaug/atelier/commit/cc4840fa330a2e2f502d322225c4b9102738bee6))
- **beads:** add epic claim and agent hook
  ([74548cc](https://github.com/shaug/atelier/commit/74548cc8628752980bdf407ae84ff75311ce0061))
- **beads:** add location discovery
  ([8d3ceef](https://github.com/shaug/atelier/commit/8d3ceef75af0f7aed954004cb232368f09f576a1))
- **beads:** add message frontmatter helpers
  ([b7babaa](https://github.com/shaug/atelier/commit/b7babaa6ff9979b2b8b409c15f4778824dc6bbe5))
- **beads:** backfill hook slots
  ([7de5bee](https://github.com/shaug/atelier/commit/7de5beebf88c63d0afccdf36df40469a4e697538))
- **beads:** close epics when complete
  ([95a1d97](https://github.com/shaug/atelier/commit/95a1d974955a351fe78a8a52870f0b9d3ceca3f0))
- **beads:** detect epic completion
  ([9fcc799](https://github.com/shaug/atelier/commit/9fcc79953d25a505bd55bece2070ae5a03adf19d))
- **beads:** isolate atelier planning store
  ([d4fd568](https://github.com/shaug/atelier/commit/d4fd56828e79e5718ad99077958867bdcd19ac50))
- **beads:** store hooks in slots
  ([9d0dea6](https://github.com/shaug/atelier/commit/9d0dea6d878f75f813d46ced2502bd4c6243ec5a))
- **changesets:** add review metadata helpers
  ([0619ead](https://github.com/shaug/atelier/commit/0619ead521b154358e273024f6a26fce06a0d613))
- **changesets:** add review update skill
  ([62dbce4](https://github.com/shaug/atelier/commit/62dbce45676c3f00b9c0ef844f344d13e211e057))
- **changesets:** derive lifecycle labels from PR state
  ([7481bef](https://github.com/shaug/atelier/commit/7481befb8a7120b15c83793929e69352d08968f0))
- **cli:** add mail command
  ([e885271](https://github.com/shaug/atelier/commit/e8852719cb005e3d7cd929681b49788494be65fc))
- **cli:** add plan/work entrypoints
  ([e6216b1](https://github.com/shaug/atelier/commit/e6216b1dea1210ddf4d653fa30d40bb58747f693))
- **cli:** add remove command for deleting project state
  ([b0e8d20](https://github.com/shaug/atelier/commit/b0e8d20193ec2b0e14a75ea96c48311ed354aa02))
- **cli:** drop legacy commands and add gc
  ([4bcfb82](https://github.com/shaug/atelier/commit/4bcfb822e1583f7a19b038498d5aef96616bc196))
- **cli:** improve worker logging and epic promotion
  ([7fe310e](https://github.com/shaug/atelier/commit/7fe310e1d407f1b87bd61e8f98308ab4db957cef))
- **cli:** replace describe with status
  ([460f50a](https://github.com/shaug/atelier/commit/460f50a9e971eb9c54906ccc7ea098beccca9b99))
- **config:** add pr strategy config and gating
  ([8dc8cd5](https://github.com/shaug/atelier/commit/8dc8cd5fc10a3aaa4cb517c098ea19a1ca8ec8bb))
- **config:** record project data dir
  ([aff65ff](https://github.com/shaug/atelier/commit/aff65ff663f3a7afa0f582d415ade8a71fc8f1d4))
- **core:** expand beads metadata and queue handling
  ([f94ea37](https://github.com/shaug/atelier/commit/f94ea376b3673a5269f8a957843e1dc192d062c8))
- **daemon:** add full-stack daemon support
  ([fa7a5d7](https://github.com/shaug/atelier/commit/fa7a5d7c36b4875a642fec9a1d5bb097392fa677))
- **epic-list:** surface dependency-blocked epics and blocker ids
  ([d80807d](https://github.com/shaug/atelier/commit/d80807d403d23a7154d6c570a84e502916703f72))
- **external-providers:** add optional sync toggles
  ([e70b94f](https://github.com/shaug/atelier/commit/e70b94f0987271f276296e2166a9691501c49a4e))
- **external-registry:** auto-discover repo beads
  ([c765f1c](https://github.com/shaug/atelier/commit/c765f1c7559f63dd7e62033fadd4aa53d4a31389))
- **external-tickets:** add enrichment fields
  ([434fb03](https://github.com/shaug/atelier/commit/434fb039a34db1fddce64d15ff02b964b557d932))
- **external-tickets:** add provider contract scaffolding
  ([a2f6f36](https://github.com/shaug/atelier/commit/a2f6f36146ee96884585297ad7ea51c52d346524))
- **external-tickets:** add schema normalization helpers
  ([f381a95](https://github.com/shaug/atelier/commit/f381a95096f31ce19ea5d4935e5d38e069b39a6f))
- **external:** add optional default auto-export for new planning beads
  ([6945f2c](https://github.com/shaug/atelier/commit/6945f2c569e446fd292589c508d72d1798998fc8))
- **gc:** add detailed reconcile and cleanup logging
  ([939cedc](https://github.com/shaug/atelier/commit/939cedccc938add86dc3853f6b9343ab99881da1))
- **gc:** prune resolved epic artifacts after integration is proven
  ([30e23a5](https://github.com/shaug/atelier/commit/30e23a50efa2224a0a07691c320280ef21401fd7))
- **gc:** release expired and closed hooks
  ([afcf188](https://github.com/shaug/atelier/commit/afcf188b20c1e1b5b681227996716d5cf3a694b9))
- **gc:** release stale queue claims
  ([199ecec](https://github.com/shaug/atelier/commit/199ecec247be2c74e7d57cef5bd3b4bdb3c19843))
- **github-issues:** add provider adapter
  ([62003cf](https://github.com/shaug/atelier/commit/62003cf9eab1f8956542beec2d298e143437353b))
- **hooks:** add hook adapter
  ([13297e8](https://github.com/shaug/atelier/commit/13297e878172d63938450afbd01a67a9a0fe14c3))
- **init:** re-run setup and ensure beads types
  ([381fc41](https://github.com/shaug/atelier/commit/381fc4196097bae5aac5e0541442be6eaee1af28))
- **init:** reconcile managed skills and fix provider prompts
  ([89cc91f](https://github.com/shaug/atelier/commit/89cc91fdff34165af05650735ab171cd6b3ce296))
- **integration:** add cas changeset integration
  ([9317261](https://github.com/shaug/atelier/commit/9317261edfae2f13182893465b2f90e8f80de58f))
- **mail:** add message bead helpers
  ([b4b9632](https://github.com/shaug/atelier/commit/b4b963267ab08c9d53788e8dcb8253a174ede8d7))
- **paths:** add project data dir helpers
  ([5a5517e](https://github.com/shaug/atelier/commit/5a5517e24f694753a83ce2fe1e534d6f3f76eb30))
- **plan:** add interactive planner flow
  ([b2924e8](https://github.com/shaug/atelier/commit/b2924e888b3572e6dc01e618d5524fe56c9277c8))
- **plan:** add on-demand planner startup overview
  ([ee23559](https://github.com/shaug/atelier/commit/ee235598e052dcec8f3db592e87bc8165ba3bfe7))
- **plan:** add planner guardrails
  ([c400678](https://github.com/shaug/atelier/commit/c400678787e59330d05a4936e2cd07d7313b8d65))
- **plan:** add planner template variables
  ([e6258a4](https://github.com/shaug/atelier/commit/e6258a4c58a72901b9d0f76522cd30d50f6b7b12))
- **plan:** add startup progress timing
  ([cc5c1fd](https://github.com/shaug/atelier/commit/cc5c1fd1530f9b9cf6c37bba334e215d85608dcb))
- **plan:** enforce planner read-only guardrails
  ([a8164ca](https://github.com/shaug/atelier/commit/a8164caea54ff5a40483b96b7b6c014918c654a8))
- **planner:** keep planner worktrees synced during active sessions
  ([3bb1461](https://github.com/shaug/atelier/commit/3bb1461fa73d1fc9bce5f40e8519bf33afcaab12)),
  closes [#99](https://github.com/shaug/atelier/issues/99)
- **planner:** surface external provider context
  ([47d190a](https://github.com/shaug/atelier/commit/47d190a24ed65335454a5975211023a7b289b1b4))
- **planning:** enforce epic-as-changeset guardrails
  ([ef6f03f](https://github.com/shaug/atelier/commit/ef6f03f5c0410c89721e8c9efd6c09028f0d5e91)),
  closes [#94](https://github.com/shaug/atelier/issues/94)
- **plan:** render planner agents template
  ([be8b7db](https://github.com/shaug/atelier/commit/be8b7db4d32b92572c02b9e1da9709b63c837363))
- **plan:** render planner agents template
  ([8fe522c](https://github.com/shaug/atelier/commit/8fe522cf5817bf6269af4ae3f7bbff3cf4ab9517))
- **plan:** start planner agent sessions
  ([2d7a214](https://github.com/shaug/atelier/commit/2d7a214a43beb11e00c0b6ea6273124c685fe9e6))
- **policy:** add role-scoped project policy beads
  ([fc9ab89](https://github.com/shaug/atelier/commit/fc9ab898784722bac7c375ae48371873a67fd447))
- **policy:** show policy by default and gate edits behind --edit
  ([68edd9f](https://github.com/shaug/atelier/commit/68edd9fc5dd09c60ee22d598a0e49cea344f09c7))
- **pr-strategy:** add on-parent-approved gating mode
  ([f2b2b82](https://github.com/shaug/atelier/commit/f2b2b82c53ac17986a0dcdb59e2b1ad6a9164b0b))
- **pr-strategy:** implement on-ready gating distinct from parallel
  ([5048e82](https://github.com/shaug/atelier/commit/5048e8256a78fa84f54ecdfec70e470ba91160e9))
- **publish:** add external ticket section to generated PR bodies
  ([b2369bb](https://github.com/shaug/atelier/commit/b2369bbec70d4ec5527c5120888f538aa9765b1a))
- **queue:** guide queue intake
  ([78a07f3](https://github.com/shaug/atelier/commit/78a07f356300a83f801f43fcb08db046856f0007))
- **repo-beads:** add export guardrails
  ([027ede2](https://github.com/shaug/atelier/commit/027ede2b01a4cd289c11dc3afd0a3792cf78e578))
- **repo-beads:** add read-only provider
  ([1501014](https://github.com/shaug/atelier/commit/1501014a43cabfbd1bf119810966783fd94d819c))
- **skills:** add agent hook workflows
  ([b8f8cdb](https://github.com/shaug/atelier/commit/b8f8cdbb356891c563e061eb8225e7d4df338da6))
- **skills:** add AgentSkills frontmatter validation gate
  ([17786be](https://github.com/shaug/atelier/commit/17786be5f53702ea3757c5633810f6421b2f3e00))
- **skills:** add beads skill scaffolding
  ([4a41b18](https://github.com/shaug/atelier/commit/4a41b18903cc39b1e7baf0251e720304bc76d299))
- **skills:** add changeset guardrail validation
  ([514f65c](https://github.com/shaug/atelier/commit/514f65c983144aed35510d163f064bec9e01f03c))
- **skills:** add epic list and claim
  ([5844707](https://github.com/shaug/atelier/commit/5844707aeada1f2d62e92359ae69b5a4a6464eeb))
- **skills:** add epic promotion skill
  ([1189c4d](https://github.com/shaug/atelier/commit/1189c4da81286accf8ef8c7be3c16e5e4d6046f7))
- **skills:** add github issues list support
  ([6d2b0d5](https://github.com/shaug/atelier/commit/6d2b0d5767094f53ae218e06063ce0845f3b5508))
- **skills:** add github-issues skill
  ([8199d77](https://github.com/shaug/atelier/commit/8199d7744fb0fff6baffeb138606def058928155)),
  closes [#88](https://github.com/shaug/atelier/issues/88)
- **skills:** add github-prs skill
  ([66b23fe](https://github.com/shaug/atelier/commit/66b23fed70edc8d29cb1cbe693d4eef0b9636795)),
  closes [#89](https://github.com/shaug/atelier/issues/89)
- **skills:** add plan_changesets
  ([450026e](https://github.com/shaug/atelier/commit/450026e6ebb43b4116745e011b64abd4d5bfb9a6))
- **skills:** add plan_create_epic
  ([558e553](https://github.com/shaug/atelier/commit/558e5535f0fee01ac555d76f1612a08aeb6d17bf))
- **skills:** add plan_split_tasks
  ([8d4c890](https://github.com/shaug/atelier/commit/8d4c890638de60ba8c5b5544b1c449d41c4f6682))
- **skills:** add planner startup check
  ([8771e7e](https://github.com/shaug/atelier/commit/8771e7e7fc3413082e098bd38eac5d40eb5bc852))
- **skills:** add startup contract
  ([464665e](https://github.com/shaug/atelier/commit/464665e70a7361d99d59b537623a2a3c6f203280))
- **skills:** add workspace-managed skills
  ([d928c5c](https://github.com/shaug/atelier/commit/d928c5c0776e38be32d1d987ec0ce86739d58f60))
- **skills:** reauthor publish workflow
  ([b14428d](https://github.com/shaug/atelier/commit/b14428d4b99889d7f07581e5f569c4e7f07a5077))
- **skills:** reauthor tickets skill
  ([f0d31b3](https://github.com/shaug/atelier/commit/f0d31b3b0a69ce624e3e94274b50583b5ffcac5f)),
  closes [#87](https://github.com/shaug/atelier/issues/87)
- **status:** add PR strategy + draft skill
  ([f80f05e](https://github.com/shaug/atelier/commit/f80f05eb07407c7d9def420e789c9e0e3c3bf26a))
- **status:** add pr strategy gating details
  ([1fcc98d](https://github.com/shaug/atelier/commit/1fcc98da3f8b7d8095a004915b4e7d7a65519ca6))
- **status:** honor cs:ready label
  ([712475b](https://github.com/shaug/atelier/commit/712475b77a243c021b53ce25661e599c80a968a7))
- **status:** report session liveness and reclaimability
  ([0c7d260](https://github.com/shaug/atelier/commit/0c7d2607ad046765ffaace7a7cf95c40b2192359))
- **status:** surface PR lifecycle signals
  ([7690bcc](https://github.com/shaug/atelier/commit/7690bcc2eecfc74cd9bfa6ec2d16d41a729fd903))
- **ticketing:** add skill-based provider detection and planner selection
  ([017efd7](https://github.com/shaug/atelier/commit/017efd7c1bdb1e879e83cceeeb3c37f9d9453edb))
- **work:** add --yes for default prompt choices
  ([0118973](https://github.com/shaug/atelier/commit/011897371ef659d08f142bfa69f2bf069063d076))
- **work:** add deterministic env-to-cli default resolver
  ([9558b0b](https://github.com/shaug/atelier/commit/9558b0bd51da4cb32ed17ab3ffd4579d0dac3a24))
- **work:** add dry-run mode for worker sessions
  ([7bedd50](https://github.com/shaug/atelier/commit/7bedd50318081357b39955b3798171cb9151fcce))
- **work:** add worker guardrails
  ([42363a6](https://github.com/shaug/atelier/commit/42363a6e8040937e150f392fe2ce5414509d29f0))
- **work:** add worker run modes
  ([960451d](https://github.com/shaug/atelier/commit/960451d68b84f6aeef5a33d8b34902c1ac3281eb))
- **work:** add worktree mapping
  ([87a1ff1](https://github.com/shaug/atelier/commit/87a1ff10179d751724a80c59c4cab9e69de21042))
- **work:** allow resume epics in prompt mode
  ([8e0b599](https://github.com/shaug/atelier/commit/8e0b599c4a760291e3625cc8d3c42ddefe8d77ba))
- **work:** check queues before claiming
  ([c2c828d](https://github.com/shaug/atelier/commit/c2c828dbb144704cf4278b590032f645214be141))
- **work:** emit per-changeset reconciliation logs
  ([535e486](https://github.com/shaug/atelier/commit/535e48688bd86ac6e64190ec085d5c13a3b48bc4))
- **work:** enforce epic claim and changeset readiness
  ([ec5c78f](https://github.com/shaug/atelier/commit/ec5c78fae2f588a420dda1a50351d662e3ef37a8))
- **work:** enforce worker completion guardrails
  ([1363116](https://github.com/shaug/atelier/commit/13631163625da006cc618466e86348d01d9821ca))
- **worker:** allow stacked intra-epic changeset selection after review handoff
  ([6b1cc9c](https://github.com/shaug/atelier/commit/6b1cc9ce6bcef49515a479696433268b472ff806)),
  closes [#93](https://github.com/shaug/atelier/issues/93)
- **worker:** enforce planner non-ownership on executable beads
  ([186ac40](https://github.com/shaug/atelier/commit/186ac4024c47683100edaaf6db38eebd99f02e77)),
  closes [#96](https://github.com/shaug/atelier/issues/96)
- **work:** fallback to unfinished epics in auto mode
  ([0c48167](https://github.com/shaug/atelier/commit/0c48167732036816d0dc1494cdcc8d13c42b6296))
- **work:** gate claims on inbox
  ([4b4b2e5](https://github.com/shaug/atelier/commit/4b4b2e5685d2b13f6389cfc9cbc80502a379ceec))
- **work:** launch agents with identity env
  ([218404c](https://github.com/shaug/atelier/commit/218404c09ea51c8dbb8ff2e9f2f8ad954780718b))
- **work:** notify overseer when idle
  ([d54b510](https://github.com/shaug/atelier/commit/d54b510bfcccfa1b9e7bf1ce36c147b2168ec280))
- **work:** prime beads before claiming
  ([02dc8c2](https://github.com/shaug/atelier/commit/02dc8c26007b4e5c8e26b0fc610e96bcd6cc7b06))
- **work:** prioritize review feedback and harden publish finalization
  ([e75d673](https://github.com/shaug/atelier/commit/e75d6734046e53890ed25d680a5cf48f3bc33926))
- **work:** reconcile blocked merged changesets on startup
  ([a0245c1](https://github.com/shaug/atelier/commit/a0245c1735d67e419011f2967af8e1e995ac10b2))
- **work:** record branch metadata
  ([9a190b5](https://github.com/shaug/atelier/commit/9a190b55e013cfee68f364257a35569be3ac9c94))
- **work:** render worker agents template
  ([c34c717](https://github.com/shaug/atelier/commit/c34c7170d04a533b4a3b3261bdf5ae4ed434d7c2))
- **work:** render worker agents template
  ([f6c733b](https://github.com/shaug/atelier/commit/f6c733bc198c93680698e2e8bccb06e788734687))
- **work:** resume hooked epics
  ([4063fc3](https://github.com/shaug/atelier/commit/4063fc38fedb73ef6800de933a195beba30997e6))
- **work:** run startup contract selection
  ([e1ecc8d](https://github.com/shaug/atelier/commit/e1ecc8da7912ff2ce12b8f85702969c8621e6be4))
- **workspaces:** pivot to epic-rooted worktrees
  ([e78edf5](https://github.com/shaug/atelier/commit/e78edf58db0583b63f172df650a49153b493ffce))
- **work:** support agent-generated squash commit subjects
  ([6384a81](https://github.com/shaug/atelier/commit/6384a8132ceccd2752666f21aed9b14425ff08ba))
- **work:** support merge and squash epic finalization
  ([89b0842](https://github.com/shaug/atelier/commit/89b084201fd85789947a810787e207b8322b0716))
- **worktrees:** add changeset worktrees
  ([098a8df](https://github.com/shaug/atelier/commit/098a8df36e9b5b06a22756753b14ced0e27f122f))
- **worktrees:** add git worktree creation
  ([f315d93](https://github.com/shaug/atelier/commit/f315d93960df838e5da08d3d8d9331ec2ba4f414))
- **worktrees:** add removal helper
  ([b594e2e](https://github.com/shaug/atelier/commit/b594e2ec95e83663c8197a90350ae39d30091ae1))
- **worktrees:** checkout changeset branches
  ([96180a1](https://github.com/shaug/atelier/commit/96180a12100c4e16109311bad2fc064df0ec1f59))
- **work:** use interactive epic selection list
  ([30a61f9](https://github.com/shaug/atelier/commit/30a61f9a4b458431e29284fe4e21ac5d1290113a))

### Bug Fixes

- **agent-home:** clean up session homes on exit and gc
  ([a8270dc](https://github.com/shaug/atelier/commit/a8270dc083bae927a1a96be2a29297be8f2bbdae))
- **agent:** add claude compat files
  ([daf4b30](https://github.com/shaug/atelier/commit/daf4b30bdba1b17cec95220e0c610ca83b50f51f))
- **agent:** keep atelier state out of worktrees
  ([b9e2fd6](https://github.com/shaug/atelier/commit/b9e2fd67825699f44e220e59369df62eea76e4cd))
- **ci:** pin ruff and align formatting output
  ([d39ec61](https://github.com/shaug/atelier/commit/d39ec611e8b7dcebbe6de518dda103f3a79d331f))
- **cli:** add global log and color flags
  ([b8c70a2](https://github.com/shaug/atelier/commit/b8c70a24298300023280147e93a6cedde3c64d15))
- **cli:** scope workspace completion
  ([86e1c91](https://github.com/shaug/atelier/commit/86e1c91c55e8564ca4b1ebb2e0120175459b7ddf))
- **gc:** handle dirty orphaned worktrees interactively
  ([47c23a3](https://github.com/shaug/atelier/commit/47c23a340471e4829577c600aba47ab729cbbdf3))
- **gc:** prompt before reconcile actions without --yes
  ([59cac88](https://github.com/shaug/atelier/commit/59cac8818497e13637a327119448c1e28e55d5f8))
- **gc:** prune closed epic artifacts without summary gating
  ([fdb15d7](https://github.com/shaug/atelier/commit/fdb15d7275ceac83bd98ff3898f271412d40106b))
- **gc:** prune integrated workspace branches without mapping metadata
  ([24536e9](https://github.com/shaug/atelier/commit/24536e976f38d052e2a44ce5850af17ce9cd1aec))
- **gc:** show reconcile cleanup targets and execution logs
  ([1880d51](https://github.com/shaug/atelier/commit/1880d515af8dce15564b4a368c8c5f2a19814ca2))
- **hooks:** skip unwritable hook paths
  ([1c3e634](https://github.com/shaug/atelier/commit/1c3e6346bae10f34e6b52e97584f323072ecdcc4))
- **init:** always prompt for external provider strategy in interactive init
  ([1a4c0ee](https://github.com/shaug/atelier/commit/1a4c0ee7a185469b2701d13c32c9c0fd920940d2))
- **init:** choose and persist external provider strategy during initialization
  ([4071afb](https://github.com/shaug/atelier/commit/4071afb2c82b78f21ba6a8743361fedbfd7a625c))
- **init:** keep enlistment repo untouched during project setup
  ([71c93be](https://github.com/shaug/atelier/commit/71c93be6cedc254ce247fdeb235e146901e8b7be))
- **lifecycle:** normalize runtime and gc changeset invariants
  ([fb4bcb9](https://github.com/shaug/atelier/commit/fb4bcb908dfdee38f8084786d0b0b77aa1fab79c))
- **open:** avoid git network hangs
  ([7ffebf4](https://github.com/shaug/atelier/commit/7ffebf40f3552af0bf31ee66d75afa75886c21ad))
- **plan:** keep planner worktree off default branch
  ([ce2dea8](https://github.com/shaug/atelier/commit/ce2dea89db61c409e2886425a2a98f6586e5b329))
- **plan:** keep startup overview refresh inside planner skill
  ([04c5e8e](https://github.com/shaug/atelier/commit/04c5e8eaa46bc1cd2e8660c8f024134ffc881e71))
- **planner:** list active epics by state in epic_list output
  ([c9cbb4a](https://github.com/shaug/atelier/commit/c9cbb4adc664b451163d89ef98ab06c8f3d1cfdd))
- **planner:** reroute inactive worker mail dispatch
  ([6264d90](https://github.com/shaug/atelier/commit/6264d902e609487aa717e6a16d45d290084bc56e))
- **plan:** prompt on dirty planner migration
  ([e28e26b](https://github.com/shaug/atelier/commit/e28e26bab05b889a734952fce283da5b6fa39701))
- **plan:** scope planner commit hook to planner worktree
  ([2a1bb66](https://github.com/shaug/atelier/commit/2a1bb661d69242d142963bc128023fbb3548bc5a))
- **reconcile:** gate plan/work reconcile and scope gc prompts to actionable
  epics
  ([b021bc8](https://github.com/shaug/atelier/commit/b021bc8a4b70415ce455fda5b2356885f6d097b8))
- **reconcile:** include closed epics pending final integration
  ([fc7f670](https://github.com/shaug/atelier/commit/fc7f6702adf8ba2fa0b2ba3f2c35779c44f8ea72))
- **repo-beads:** resolve lint/test issues
  ([2a78f46](https://github.com/shaug/atelier/commit/2a78f46aa6fa304bccc5bdef1943701de6317c76))
- **repo:** address PR review feedback on hook bootstrap
  ([bac4204](https://github.com/shaug/atelier/commit/bac4204e3b5dd6bd04f9355dc6b13d2ca6aa7be3))
- **session:** harden stale worker detection against pid reuse
  ([80f1a17](https://github.com/shaug/atelier/commit/80f1a17927ca370155540caf0cd174a010f55515))
- **skills:** add frontmatter to github skill doc
  ([8774257](https://github.com/shaug/atelier/commit/87742572bea57e15ecdd79cdff3652b63efbd930))
- **skills:** enforce strict AgentSkills validation gate
  ([bdcb312](https://github.com/shaug/atelier/commit/bdcb3121b90cb7d8902bce6b906fc20d6b93210a)),
  closes [#109](https://github.com/shaug/atelier/issues/109)
- **skills:** remove unsupported Actor.isBot field from review thread query
  ([d4e2a27](https://github.com/shaug/atelier/commit/d4e2a27f949a5c7d014cf7430b50eee48a0fcd49))
- **ticketing:** detect legacy provider skills without manifests
  ([4538ebd](https://github.com/shaug/atelier/commit/4538ebd230c509b3976647eacdb3a61be0fceee0))
- **ticketing:** use known provider skills instead of manifest files
  ([4143e0d](https://github.com/shaug/atelier/commit/4143e0d3da605560100a2f1aa1bd1acdb4149e30))
- **work:** accept git-graph integration signals for merged changesets
  ([8066af1](https://github.com/shaug/atelier/commit/8066af100bd52d2b071e2ab5ace06f4dedb773a2))
- **work:** accept integration sha from bead notes
  ([c735ea4](https://github.com/shaug/atelier/commit/c735ea49936a2b0d10ae4a550bcdbe6d42f9e1bb))
- **work:** allow direct epic execution without child changesets
  ([4ad0bc2](https://github.com/shaug/atelier/commit/4ad0bc269c2d028c0683c820dc3f02386b280f42))
- **work:** auto-sync managed skills and finalize pushed changesets
  ([5122249](https://github.com/shaug/atelier/commit/5122249ed80fc36bb54038ac325ab9c50dd03a80))
- **work:** classify pushed-without-pr finalize failures
  ([a737ae3](https://github.com/shaug/atelier/commit/a737ae32c627eaa2419a4ceccd45b6ec1af6bde7))
- **work:** continue past review-pending in-progress changesets
  ([8af70ab](https://github.com/shaug/atelier/commit/8af70abee661f0497f5c9b12bc8f07c8760d5606))
- **work:** create missing PRs during worker finalization
  ([a29a696](https://github.com/shaug/atelier/commit/a29a696ebbf195a147d6b81900677b032b06b9a1))
- **work:** derive PR base from epic parent for first changesets
  ([d317a0a](https://github.com/shaug/atelier/commit/d317a0ad4aacb9a94373864a3bfa9b4aadabd390))
- **work:** derive top-level PR base from workspace parent branch
  ([f790b08](https://github.com/shaug/atelier/commit/f790b08b6f45524c724573454518f00ddeeb778b))
- **work:** detect inline PR comments in feedback prioritization
  ([f20c0b2](https://github.com/shaug/atelier/commit/f20c0b2c6c1d7a112d7d8286f73a9245dae65e07))
- **work:** detect integration sha in notes payloads
  ([7f8fb5b](https://github.com/shaug/atelier/commit/7f8fb5b459bd0237c5a2f14b5d8bde46332f85f9))
- **work:** distinguish missing PRs from PR query failures
  ([ed195bc](https://github.com/shaug/atelier/commit/ed195bc1273ad198bd27f79e128dcace6afd447e))
- **work:** enforce feedback progress before completing review runs
  ([ee03b01](https://github.com/shaug/atelier/commit/ee03b01b59dafa0cdceee0f5b7c3637a89af0a43))
- **work:** enforce inline review-thread replies in feedback runs
  ([a02591e](https://github.com/shaug/atelier/commit/a02591eeebd23836bd1f3a76c7b062783289ae34))
- **work:** enforce pr-required publish lifecycle
  ([6d0c5a4](https://github.com/shaug/atelier/commit/6d0c5a4c0f7569bc0099498a27d8f68f912f6af8))
- **work:** enforce startup feedback and work precedence
  ([e0734f7](https://github.com/shaug/atelier/commit/e0734f701504f0dc3084b2a7665b6daf0a450bbe))
- **worker:** align finalize PR-create callback contract
  ([b351206](https://github.com/shaug/atelier/commit/b3512060e34c6ff19b3e2fc1213c96f73e4a792c))
- **worker:** align PR base to parent lineage
  ([42b1580](https://github.com/shaug/atelier/commit/42b158009a756686892844f69ac612e50772e485)),
  closes [#112](https://github.com/shaug/atelier/issues/112)
- **worker:** avoid failing on stable changeset base metadata
  ([082e150](https://github.com/shaug/atelier/commit/082e15074e8bb4bc608b3fa1c2135bf9524aa74e))
- **worker:** avoid false review-feedback stalls
  ([049543b](https://github.com/shaug/atelier/commit/049543b007c8d6375e93075400cfbd1c06af3b28))
- **worker:** detect default-branch merge conflicts in review checks
  ([b756635](https://github.com/shaug/atelier/commit/b756635966461ceb8e73203a3376e9c521b91531))
- **worker:** harden helper module compatibility lookups
  ([eb195df](https://github.com/shaug/atelier/commit/eb195df4c014f80c805856717ba52fbc8eb021e2))
- **worker:** harden sequential PR gating lineage resolution
  ([a18ea81](https://github.com/shaug/atelier/commit/a18ea81aae466e3276087a30e7e65789562bbc33)),
  closes [#129](https://github.com/shaug/atelier/issues/129)
- **worker:** hydrate changesets before review-feedback selection
  ([d520d5e](https://github.com/shaug/atelier/commit/d520d5e70a1435908f05be58d71fcfc2547e9a03))
- **worker:** restore watch interval default constant
  ([faf8141](https://github.com/shaug/atelier/commit/faf814144319124dd0e801222063db590cc4edc4))
- **worker:** skip unclaimable review feedback epics
  ([6d3df01](https://github.com/shaug/atelier/commit/6d3df0185e7713026e5bcd294fc9e059438fea99))
- **work:** fall back to global ready changesets
  ([b7798e7](https://github.com/shaug/atelier/commit/b7798e79690b5d1cf0519052a6825fe69f8844db))
- **work:** finalize epic integration from owning worktree context
  ([1b8f5a0](https://github.com/shaug/atelier/commit/1b8f5a07d46d75680cf161666a629ee7f416e00f))
- **work:** finalize non-pr epics to parent branch
  ([f5f46b8](https://github.com/shaug/atelier/commit/f5f46b8920b4067149a47d3cb086b65696c62081))
- **work:** harden worker lifecycle and changeset validation
  ([0713af4](https://github.com/shaug/atelier/commit/0713af408385e448291699316e90d76320c869af))
- **work:** include global review-feedback candidates in startup
  ([7d3cb1c](https://github.com/shaug/atelier/commit/7d3cb1c439734e046fae1fda03811d86c5d79c12))
- **work:** keep parent changesets open while subtasks remain
  ([8168c89](https://github.com/shaug/atelier/commit/8168c8917d854917169f5b768fc15f7744d849b0))
- **work:** keep review-feedback changesets actionable and explicit
  ([f4445ab](https://github.com/shaug/atelier/commit/f4445ab6c9552f1e8fe9657499c15fe730225ed4))
- **work:** keep review-pending epics open and improve PR fallback content
  ([4e35679](https://github.com/shaug/atelier/commit/4e3567980e6df5866ebcf1b542601c71feef75b5))
- **work:** make reconciliation dependency-aware for merged changesets
  ([77ccddd](https://github.com/shaug/atelier/commit/77ccddd5862f71ea30f17bab84495f6c907b6ce7))
- **work:** persist review feedback cursor after feedback runs
  ([b04b2b5](https://github.com/shaug/atelier/commit/b04b2b53b1d97ff6b49f62807a727a4f6e776970))
- **work:** prefer live PR state for feedback candidate selection
  ([d512b2c](https://github.com/shaug/atelier/commit/d512b2c460853fcd9d357e8338daef383f08015c))
- **work:** prefer live PR state over stale review metadata
  ([b1edb53](https://github.com/shaug/atelier/commit/b1edb53c3ddc335c1195a966762961eb312ce82d))
- **work:** prefer oldest assigned epic
  ([532bce7](https://github.com/shaug/atelier/commit/532bce72e569de86c047aef9610b82c8bac6c703))
- **work:** prevent top-level PR gating deadlocks
  ([fb879fa](https://github.com/shaug/atelier/commit/fb879faa2a2efefcfff3b5ed4ef3d149d9e2629d))
- **work:** promote planned subtasks after parent completion
  ([64a97f6](https://github.com/shaug/atelier/commit/64a97f62b0804754a21cec15046aa10dd0475319))
- **work:** reclaim stale assignee on review feedback pickup
  ([6333398](https://github.com/shaug/atelier/commit/63333988b847183aac1e24e8a1a6786357ff7060))
- **work:** reclaim stale same-family worker claims
  ([d896de5](https://github.com/shaug/atelier/commit/d896de547ec8aa404691aad54773e4b561c1d3c6))
- **work:** recover premature cs:merged states into PR lifecycle
  ([e7c4f1e](https://github.com/shaug/atelier/commit/e7c4f1e9de1add79896e9e5af163f7558f39025e))
- **work:** recover when PR exists after create failure
  ([f8c3d4f](https://github.com/shaug/atelier/commit/f8c3d4f54311b48eaaca659f88567cde023df646))
- **work:** resume assigned epics before inbox
  ([52b6c09](https://github.com/shaug/atelier/commit/52b6c098ba4d4ce6f1a9c0645ace20bf4bae1a20))
- **work:** resume blocked changesets with publish signals
  ([8d391e9](https://github.com/shaug/atelier/commit/8d391e9310754c2e57465ee228c4ff83c58bb79b))
- **work:** retry blocked in-review changesets during feedback pickup
  ([0b3fd60](https://github.com/shaug/atelier/commit/0b3fd607b4795727b603f21fa873142d69b15019))
- **work:** run codex workers in non-interactive exec mode
  ([2046b03](https://github.com/shaug/atelier/commit/2046b03b60357c1c989c7ba6cf4b99b2466beb3b))
- **work:** run epic-as-changeset on the epic root branch
  ([155c616](https://github.com/shaug/atelier/commit/155c6165370140cb26d3533c80f186c22e082f7e))
- **work:** skip draft and assigned fallback ready-epics
  ([6c2f66c](https://github.com/shaug/atelier/commit/6c2f66c0ca5ab731830f58ac91e6df05ccda05ce))
- **work:** skip stalled epics and continue selecting work
  ([efc8683](https://github.com/shaug/atelier/commit/efc868346cb77d440d68ba73d2585971a3f54ebc))
- **work:** stabilize worker startup and ready-state flow
  ([8f9c4f2](https://github.com/shaug/atelier/commit/8f9c4f27f9470d88354fcbd3f7765bb28204d531))
- **work:** terminalize merged and closed PR changesets
  ([7e08338](https://github.com/shaug/atelier/commit/7e08338f5de17526e3569cfdc0307d4606043c23))
- **work:** tighten startup selection for draft and blocked feedback cases
  ([71b27b3](https://github.com/shaug/atelier/commit/71b27b3936352f608e6c3cd9137e2319475ef176))
- **work:** treat in-progress changesets as runnable
  ([445f33c](https://github.com/shaug/atelier/commit/445f33cba4b88f2d1aecc75712ef12c64eadf695))
- **worktrees:** create epic worktree from root branch
  ([c35e633](https://github.com/shaug/atelier/commit/c35e633c1cd39a16782e71f427903eb791f88462))
- **worktrees:** materialize root branch before changeset setup
  ([7125644](https://github.com/shaug/atelier/commit/7125644387c2dc9b2c850b6a312c530f615ae14e))
- **worktrees:** reconcile stale root-branch mappings
  ([7d25b5f](https://github.com/shaug/atelier/commit/7d25b5f5f8ca85d62e591b4b5d0bd6ece98b3476))
- **work:** use status-driven changeset readiness and normalize labels
  ([35d027b](https://github.com/shaug/atelier/commit/35d027b3a90bfede578c204d0da0a3bb7f4499ee))
- **work:** validate integrated sha claims against git graph
  ([857fa71](https://github.com/shaug/atelier/commit/857fa7100faf39128776a476e52f966d2bf40b7b))

### Performance Improvements

- **prs:** add bounded retries and runtime PR query caches
  ([a5be993](https://github.com/shaug/atelier/commit/a5be993796032d628b7a95248a6f18a7ca6f1339))

## [0.6.0](https://github.com/shaug/atelier/compare/v0.5.0...v0.6.0) (2026-01-26)

### Overview

This release expands day-to-day workspace operations while tightening migration
and upgrade behavior. Atelier adds `new`, `describe`, and improved remove/clean
flows, plus ticket-aware workspace defaults and identity/base-SHA tracking to
make branch intent clearer. It also introduces optional terminal adapters and
drops snapshot workflows, marking the transition toward more explicit,
branch-driven project state management.

### ⚠ BREAKING CHANGES

- remove atelier snapshot command and related tests.

### Features

- add atelier new command
  ([8a6c4ad](https://github.com/shaug/atelier/commit/8a6c4ad4b490ce7161beba250d3fd2392109fa85))
- add workspace snapshot command
  ([a8364d0](https://github.com/shaug/atelier/commit/a8364d048c565b78d9d0f937fe76463371746cb7))
- **ai:** add optional helpers for workspace open
  ([7e87f39](https://github.com/shaug/atelier/commit/7e87f3911dd4013956ea537a1bc65c9ab26714f7))
- **clean:** add dry-run preview
  ([62bcadd](https://github.com/shaug/atelier/commit/62bcaddd2ab0446fe40e0ab4f9490b153d80f03d))
- **cli:** add describe command
  ([808ac4d](https://github.com/shaug/atelier/commit/808ac4dbad63a261265b7789982229929a01d5ed)),
  closes [#46](https://github.com/shaug/atelier/issues/46)
- **cli:** add remove command and orphan cleanup
  ([c6f577a](https://github.com/shaug/atelier/commit/c6f577a52d6526ce982e751e6210a11549f8560b)),
  closes [#51](https://github.com/shaug/atelier/issues/51)
- **cli:** add workspace root option
  ([9b2de34](https://github.com/shaug/atelier/commit/9b2de342b767fafe9c20f89581e2b92957ef6cc2)),
  closes [#47](https://github.com/shaug/atelier/issues/47)
- **cli:** complete workspace names
  ([3fde23b](https://github.com/shaug/atelier/commit/3fde23b081470ac2921bf7a814c0ce605e69bf4a))
- **codex:** capture session id via pty
  ([75297bb](https://github.com/shaug/atelier/commit/75297bb0fc089d59e73b6514fd295fd05807fefd)),
  closes [#33](https://github.com/shaug/atelier/issues/33)
- **config:** add git path and provider metadata
  ([4cee306](https://github.com/shaug/atelier/commit/4cee30654360371a448ec84c1feca6be691eb946)),
  closes [#44](https://github.com/shaug/atelier/issues/44)
- **config:** add ticket support
  ([6b7e5f1](https://github.com/shaug/atelier/commit/6b7e5f1293df50027d8cdf990c06db9709918c36))
- **open:** add per-invocation yolo flag
  ([393b71a](https://github.com/shaug/atelier/commit/393b71a3e5cff1ed6143b85b99466c939c22772b))
- **open:** derive ticket workspace names
  ([3015e21](https://github.com/shaug/atelier/commit/3015e21c9881fdaced9a5f904bd299f2538e4862))
- **open:** enhance ticket workspace defaults
  ([336ef38](https://github.com/shaug/atelier/commit/336ef38d2dc9d6e4209bbe45f0c1f7242b7752ac))
- remove snapshot command
  ([5e8224b](https://github.com/shaug/atelier/commit/5e8224bdd96775c82dc432b378837d2f16e6e259))
- **templates:** align upgrade comparisons
  ([daa3aeb](https://github.com/shaug/atelier/commit/daa3aebc025acbde09c2afe0cc460bd709c304d9)),
  closes [#73](https://github.com/shaug/atelier/issues/73)
- **term:** add iTerm2 title adapter
  ([b807538](https://github.com/shaug/atelier/commit/b807538acd2fb0d2eed75f2c5b92d915870cc60b))
- **terminal:** add optional terminal adapter layer
  ([c3930da](https://github.com/shaug/atelier/commit/c3930da97f0badf70f171db9438a76d4a70573b5)),
  closes [#60](https://github.com/shaug/atelier/issues/60)
- **test:** add curated doctest collection
  ([1f78691](https://github.com/shaug/atelier/commit/1f786916dcd945a1ce31f036e6f42ec7d4f601ff))
- **workspace:** add workspace identity helpers
  ([35153ca](https://github.com/shaug/atelier/commit/35153cadd278d9c8985a27425f5e0144c02d8699)),
  closes [#50](https://github.com/shaug/atelier/issues/50)
- **workspaces:** remove legacy WORKSPACE.md support
  ([9532515](https://github.com/shaug/atelier/commit/953251534bace38581acc4d4cbf390cc707e40ae)),
  closes [#34](https://github.com/shaug/atelier/issues/34)
  [#35](https://github.com/shaug/atelier/issues/35)
- **workspace:** track base sha for committed work
  ([11d0358](https://github.com/shaug/atelier/commit/11d03589d71db266e8173a6dc40ca3ea2eb5f82c))

### Bug Fixes

- **clean:** guard remote branch deletion
  ([5897248](https://github.com/shaug/atelier/commit/5897248ac7fc47dacd8c7fb5cc1e6563ab666d0e))
- **cli:** fallback to branches when no workspaces
  ([7d56258](https://github.com/shaug/atelier/commit/7d562589b31ed17b2f391d9880ce74509d96223e))
- **cli:** handle shell completion env
  ([b779970](https://github.com/shaug/atelier/commit/b77997001b4566ad6e02cd56e3710f7c9c7b91f2))
- **cli:** show completion options
  ([818e6de](https://github.com/shaug/atelier/commit/818e6de3df438700f9004968194c335cdf7f84d6))
- **codex:** sync pty window size
  ([6d33456](https://github.com/shaug/atelier/commit/6d33456c336d9313d1b311fce95de1c2709c73d9))
- **exec:** normalize editor command inputs
  ([bd6107a](https://github.com/shaug/atelier/commit/bd6107ad18d59b69be6bfd1d96b7f8f33380c4c6)),
  closes [#59](https://github.com/shaug/atelier/issues/59)
- isolate codex sessions per workspace uid
  ([82ff375](https://github.com/shaug/atelier/commit/82ff375b774f7f9f3ee9c7699fe7f780a4464521))
- **open:** clear finalization tags in both repos
  ([b759186](https://github.com/shaug/atelier/commit/b75918694b02a68bf973279fbcaa4b5631cad26f)),
  closes [#70](https://github.com/shaug/atelier/issues/70)
- **open:** open success doc for new workspaces
  ([9e26f52](https://github.com/shaug/atelier/commit/9e26f524da0308e5ca3f3906599f34fc5b3d09a3)),
  closes [#38](https://github.com/shaug/atelier/issues/38)
- **open:** prefer exact branch matches
  ([89091e2](https://github.com/shaug/atelier/commit/89091e258423fdd958eb6fd82e8dd4e58266db3b)),
  closes [#58](https://github.com/shaug/atelier/issues/58)
- prefer exact branch matches in open
  ([00f7f4b](https://github.com/shaug/atelier/commit/00f7f4b3453dfa9208a028a96a90c8ddc24895b5))
- **sessions:** require exact workspace token
  ([503e60a](https://github.com/shaug/atelier/commit/503e60a5862ef57ce6d42b32644fac2d749bad31)),
  closes [#53](https://github.com/shaug/atelier/issues/53)
- **sessions:** scan jsonl for session_meta
  ([bf2a29a](https://github.com/shaug/atelier/commit/bf2a29a9940c58010cdabdd86a9f62c301cb2264)),
  closes [#71](https://github.com/shaug/atelier/issues/71)
- **shell:** normalize --shell override
  ([9fe023d](https://github.com/shaug/atelier/commit/9fe023de2fd8685873c31d4dc0aea87d508d9288))
- **template:** honor installed cache for template rendering
  ([1a1f3b3](https://github.com/shaug/atelier/commit/1a1f3b33708379389af7de049999da4455718925)),
  closes [#40](https://github.com/shaug/atelier/issues/40)
- **upgrade:** handle orphaned workspace configs
  ([d5ba536](https://github.com/shaug/atelier/commit/d5ba536f9d1e3c66988a28e856bb3dcd6a1d41c8)),
  closes [#57](https://github.com/shaug/atelier/issues/57)
- **upgrade:** migrate tickets in legacy config
  ([d29c30e](https://github.com/shaug/atelier/commit/d29c30ee38b00a3625b73b10b31cd67dc5e56b92))
- **upgrade:** prompt on modified files
  ([f89e04b](https://github.com/shaug/atelier/commit/f89e04bfcec17accbc5d31767ccfb27efe33c781))
- **upgrade:** prompt to remove legacy AGENTS
  ([2d5183a](https://github.com/shaug/atelier/commit/2d5183a23cffd7b24a68ab9ffd7582e0fde6e4d5))
- **wezterm:** set pane title via OSC
  ([c6d67eb](https://github.com/shaug/atelier/commit/c6d67eb794f90665f752102fd489987058d47928))

### Performance Improvements

- **cli:** speed workspace completions
  ([3e2ef97](https://github.com/shaug/atelier/commit/3e2ef97ccf3c2ea999f8796170a38fe3ab0b5f04))

### Miscellaneous Chores

- release 0.6.0
  ([d311b77](https://github.com/shaug/atelier/commit/d311b7798ddd9e27962b77fed22e08f619e18154))

## [0.5.0](https://github.com/shaug/atelier/compare/v0.4.0...v0.5.0) (2026-01-21)

### Overview

This release rounds out the workspace lifecycle and agent integrations: new
SUCCESS.md contracts, background/persist files, and clean finalization tagging
make workspaces more self-describing and easier to manage. The CLI and config
system level up with new config/template/edit and upgrade commands, a split
sys/user configuration model backed by pydantic, and workspace shell/exec plus
editor role support. On the agent side, resume support expands (Claude, Gemini
CLI, Copilot), and a handful of fixes smooth out config recovery, formatting,
and edge-case CLI behavior.

### Features

- add claude resume support
  ([8c6b54f](https://github.com/shaug/atelier/commit/8c6b54f22a5792c1bdc6772b68164c3d45800352))
- add config/template/edit commands
  ([0190934](https://github.com/shaug/atelier/commit/019093491a4edc77afe5fa78288c81df6ca89375)),
  closes [#22](https://github.com/shaug/atelier/issues/22)
- add persist/background workspace files
  ([e9e3160](https://github.com/shaug/atelier/commit/e9e3160a5ad3ab56cc9bc90b05a236b6a5882a04))
- add pydantic config models
  ([cb0438d](https://github.com/shaug/atelier/commit/cb0438dea03ef380a7d464d296f798ea2f94fbb6))
- add SUCCESS.md workspace contract
  ([b4f4955](https://github.com/shaug/atelier/commit/b4f49555edca66307441bef66ffc7bfe4c8b172b))
- add template upgrade policy
  ([e71de1e](https://github.com/shaug/atelier/commit/e71de1e01a8364532a6424eff11a63a126e58188))
- add upgrade command and template cache
  ([cc02362](https://github.com/shaug/atelier/commit/cc02362dfe9eab92ce068e3d5c55230f9dd35f7e))
- **agent:** add aider support
  ([519cc36](https://github.com/shaug/atelier/commit/519cc36448eb94bfb00deaa7c5508bf4aaa3efb6))
- **agent:** add gemini cli resume
  ([ec37503](https://github.com/shaug/atelier/commit/ec37503c6250b1c504a7b0e19c95aac7eed878f0)),
  closes [#26](https://github.com/shaug/atelier/issues/26)
- **agents:** finalize copilot support
  ([93257a3](https://github.com/shaug/atelier/commit/93257a3772f7a8b9c0eca6c7546eea859380a815)),
  closes [#27](https://github.com/shaug/atelier/issues/27)
- **cli:** add editor roles and work command
  ([23d7f52](https://github.com/shaug/atelier/commit/23d7f5221b242ead538c42fc797d495c68edd929)),
  closes [#29](https://github.com/shaug/atelier/issues/29)
- **cli:** add workspace shell and exec commands
  ([88e23c3](https://github.com/shaug/atelier/commit/88e23c3c0839d535df1c926bce72c21ffb0a4f3c)),
  closes [#30](https://github.com/shaug/atelier/issues/30)
- **config:** split sys/user config files (Fixed
  [#23](https://github.com/shaug/atelier/issues/23))
  ([340d7a6](https://github.com/shaug/atelier/commit/340d7a6d0e8eb6d6ff7818baf80f16779385ecb9))
- configure agent launching
  ([45a1296](https://github.com/shaug/atelier/commit/45a1296b91bc80ea96266df04b12b0623bbe361e)),
  closes [#24](https://github.com/shaug/atelier/issues/24)
- consolidate workspace policy files
  ([25141d6](https://github.com/shaug/atelier/commit/25141d6ee12b9bd0ef31009526b9f9a18ee0074a))
- gate clean on finalization tag
  ([423c385](https://github.com/shaug/atelier/commit/423c385091732d2ffff7d08274fdf83dcbd02ab5))
- identify projects by enlistment path
  ([06c880c](https://github.com/shaug/atelier/commit/06c880c0381345bd47db34d143809a25c92b9924))
- migrate cli to typer
  ([7b14260](https://github.com/shaug/atelier/commit/7b14260250f8bc579465818997ed8de6d995d5d9))
- shift workspace intent to WORKSPACE.md
  ([81f9dc3](https://github.com/shaug/atelier/commit/81f9dc344a795043cf72f6bc9ad6274945837649))
- use select prompts for config choices
  ([40a478b](https://github.com/shaug/atelier/commit/40a478bcb2f7d1f25fbe1192368afba9489d32f8))

### Bug Fixes

- **config:** recover from legacy and missing workspace configs
  ([a103969](https://github.com/shaug/atelier/commit/a1039694d04fc404bc14dd570348e20ab694990b))
- do not reapply branch prefix when already present
  ([65f79d6](https://github.com/shaug/atelier/commit/65f79d67a03f5e9d9e894fbd392e1e3542f67e75))
- fix the code and md formatting
  ([ea156fb](https://github.com/shaug/atelier/commit/ea156fb7d0eb520f85d5ebda823487e10a06c41e))
- match codex session prompt from event_msg
  ([5477f76](https://github.com/shaug/atelier/commit/5477f76e03c74f21fa4bb81cd81c9e6bf4c9e808))
- open workspace AGENTS.md in editor
  ([ac570a6](https://github.com/shaug/atelier/commit/ac570a617c443f00e139f8e96b5a6db02f8bcdf1))
- refresh tool install deps
  ([0e177e3](https://github.com/shaug/atelier/commit/0e177e3b75ed35cc06abe88c1e50b88315bc9d55))

## [0.4.0](https://github.com/shaug/atelier/compare/v0.3.0...v0.4.0) (2026-01-17)

### Overview

This release is a focused simplification pass. Default-branch selection moves to
runtime derivation and Atelier state/default handling is reduced, making project
setup and command behavior less config-heavy while preserving the new policy and
workflow scaffolding introduced in 0.3.x.

### Features

- derive default branch at runtime
  ([0140a4f](https://github.com/shaug/atelier/commit/0140a4ffecd290b922e0e88ccde10c81bd80c5fe))
- simplify atelier state and defaults
  ([6290250](https://github.com/shaug/atelier/commit/62902501eeb30b6239a7a8d705a86504ff61c0d6))

## [0.3.0](https://github.com/shaug/atelier/compare/v0.2.0...v0.3.0) (2026-01-15)

### Overview

This release establishes the first practical policy-driven workflow layer.
Atelier adds branch-policy controls in `open`, list/clean/status quality-of-life
commands, init prompt flags, and release/versioning guardrails, then follows
through with fixes around origin checks, workspace policy rendering, and
open-time behavior when repositories are missing or inputs are ambiguous.

### Features

- add branch policy overrides to open
  ([e596783](https://github.com/shaug/atelier/commit/e5967831d52044d39758b18d62feecf48dcda410))
- add cleanup and status options
  ([90d98bc](https://github.com/shaug/atelier/commit/90d98bcd974a157b99de821e56481c68bd0f9df8))
- add policy overlay stubs
  ([dc03b82](https://github.com/shaug/atelier/commit/dc03b8239a96aca0c22456e738bcf929342d491e))
- add policy overlay templates
  ([5314958](https://github.com/shaug/atelier/commit/53149586cf6fefe49668ae3ce05d913494ec495c))
- add versioning process
  ([6c00604](https://github.com/shaug/atelier/commit/6c0060429bd8c08d7bd5d5e71870d3e5eb160bfb))
- append branch summary on workspace open
  ([597273b](https://github.com/shaug/atelier/commit/597273bf33a335651d22867bbdafe29e53624059))
- **cli:** add list and clean workspace commands
  ([9b6f7a1](https://github.com/shaug/atelier/commit/9b6f7a14d29c06fb0eaa1fe6242f8c9df84746c1))
- **init:** add flags for prompt values
  ([da251ae](https://github.com/shaug/atelier/commit/da251aedaeb143cccf03eef99b1d492fff61a893))
- normalize workspace names
  ([28e98ad](https://github.com/shaug/atelier/commit/28e98adfa71c4c16c4b75f47b9dfc4e7ec86c0ad))
- **open:** add branch override flag
  ([bc18e11](https://github.com/shaug/atelier/commit/bc18e11fd8fbe3b128a9c4993b72a7f4ef745470))
- parallelize workspace status collection
  ([2a5c123](https://github.com/shaug/atelier/commit/2a5c123319c05ea32355911154b9949350c33055))
- prompt branch settings on init
  ([fbd932e](https://github.com/shaug/atelier/commit/fbd932ecfbef98a2d641d1d1f4846699acbfa84b))

### Bug Fixes

- correct workspace policy indentation
  ([76a4b83](https://github.com/shaug/atelier/commit/76a4b83c009a3d575298db1f2ed5834322711bee))
- enforce origin check and use workspace settings
  ([513c24b](https://github.com/shaug/atelier/commit/513c24ba45606c453e3dfaaf09f9d86649b0272f))
- open AGENTS before clone when repo missing
  ([8489fff](https://github.com/shaug/atelier/commit/8489fff6cfc28be70934d51c68282789a0a48626))
- strip workspace root from inputs
  ([396fa38](https://github.com/shaug/atelier/commit/396fa38a3eae61173a04437fa2f0fca1543c2f0a))

## [0.2.0]

- Initial release.
