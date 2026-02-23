# GitHub issues via gh CLI

## Required gh commands

- Create:
  `gh issue create --repo <OWNER/REPO> --title <title> --body-file <path> [--label <label>]`
- Read: `gh issue view <issue> --repo <OWNER/REPO> --json <fields>`
- Update:
  `gh issue edit <issue> --repo <OWNER/REPO> [--title <title>] [--body-file <path>] [--add-label <label>] [--remove-label <label>]`
- Close:
  `gh issue close <issue> --repo <OWNER/REPO> [--comment <comment>] [--reason completed|not planned]`

## JSON fields used by scripts

- number
- title
- body
- state
- url
- labels
- assignees
- author
