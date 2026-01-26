# Changelog

## [0.6.0](https://github.com/shaug/atelier/compare/v0.5.0...v0.6.0) (2026-01-26)

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

### Features

- derive default branch at runtime
  ([0140a4f](https://github.com/shaug/atelier/commit/0140a4ffecd290b922e0e88ccde10c81bd80c5fe))
- simplify atelier state and defaults
  ([6290250](https://github.com/shaug/atelier/commit/62902501eeb30b6239a7a8d705a86504ff61c0d6))

## [0.3.0](https://github.com/shaug/atelier/compare/v0.2.0...v0.3.0) (2026-01-15)

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
