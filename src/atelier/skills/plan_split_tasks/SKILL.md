---
name: plan_split_tasks
description: >-
  Split an epic into task and subtask beads with appropriate labels.
---

# Plan split tasks

## Inputs

- epic_id: Parent epic bead id.
- tasks: List of task titles and acceptance criteria.
- subtasks: Optional subtasks mapped to a task.
- beads_dir: Optional Beads store path.

## Steps

1. Create task beads under the epic:
   - `bd create --parent <epic_id> --type task --label at:task --title <title> --acceptance <acceptance>`
1. Create subtasks under the task when needed:
   - `bd create --parent <task_id> --type task --label at:subtask --title <title> --acceptance <acceptance>`
1. Use `--notes` for follow-up details instead of editing descriptions.

## Verification

- Tasks and subtasks appear under the epic with correct labels.
