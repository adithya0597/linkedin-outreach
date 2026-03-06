## Parallel Work Rules

### Separate Instances
- Each Claude Code instance should work in its own scope
- Use git worktrees or separate directories for parallel code changes
- Never have two instances modifying the same file simultaneously

### Task Isolation
- Each instance owns a distinct task (e.g., one scans portals, another drafts outreach)
- Coordinate via shared files: HANDOFF.md, task files in tasks/
- Use file locks or conventions to prevent conflicts

### Handoff Between Instances
- Write HANDOFF.md before stopping or context-switching
- Include: current state, what's done, what's next, any blockers
- The next instance reads HANDOFF.md first before starting work

### Subagent Parallelism
- Use subagents for independent queries (company research, LinkedIn lookups)
- Coordinator sees summaries only — never full subagent traces
- Match subagent type to needed tools (read-only for research, full for writes)
