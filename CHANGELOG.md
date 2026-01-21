# Changelog

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
