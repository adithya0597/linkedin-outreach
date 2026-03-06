## Verification Standards

### Every Task Must End with Verification
- After writing to Notion: query back to confirm the write succeeded
- After drafting outreach: validate character counts (connection ≤300, InMail ≤400)
- After scanning portals: cross-reference results against existing target list for dedup
- After modifying CLAUDE.md: re-read the file to confirm changes are correct
- After creating files: verify they exist and contain expected content

### Long-Running Task Protocol
- For tasks expected to run >2 minutes: use exponential backoff polling (1m → 2m → 4m → 8m)
- Never spin-wait on external APIs; always use backoff
- If a task exceeds 8 minutes without progress, stop and report status

### Context Management
- Before context reaches 85%, run /handoff to preserve state
- The Stop hook (check-context.sh) will block at 85% and suggest /half-clone
- Always write intermediate results to disk, not just context

### Verification Checklist Template
When completing any significant task, verify:
1. **Data written** — Can you read back what you wrote?
2. **Constraints met** — Character limits, formatting rules, required fields
3. **No regressions** — Existing data not corrupted or overwritten
4. **Consistent state** — Local files and Notion CRM agree
