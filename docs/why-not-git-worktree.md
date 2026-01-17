# Why not `git worktree`?

`git worktree` is a great tool. It makes multiple checkouts efficient and keeps
disk usage low. Atelier simply solves a different problem.

Atelier's primary abstraction is a *workspace*: a unit of intent, execution, and
lifecycle. That includes how work is launched, how agent context is captured,
and how the workspace is cleaned up when the work is done.

`git worktree` operates at the checkout layer. It optimizes storage by sharing
state across worktrees, which can be convenient but also creates invisible
coupling between environments.

Atelier intentionally chooses full clones to keep isolation explicit and
predictable. Independent repositories make cleanup simpler and reduce the chance
of shared state surprising humans or agents.

Disk is cheap. Cognitive overhead and invisible coupling are not.
