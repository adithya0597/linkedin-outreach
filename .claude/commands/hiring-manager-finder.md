---
name: hiring-manager-finder
description: "**Hiring Manager Finder**: Searches LinkedIn for CTOs, VPs of Engineering, Engineering Managers, and Recruiters at a target company. Returns name, title, LinkedIn degree, follower count, and recent posts for pre-engagement planning. Use this skill whenever the user says 'find hiring manager', 'who's hiring at [company]', 'find the CTO', 'look up engineering leadership', 'who should I reach out to at [company]', or when a new company passes validation and the next step is identifying who to contact. Also trigger after a portal scan discovers new companies — the natural next step is finding who to message."
---

# Hiring Manager Finder

Find the right person to contact at a target company for LinkedIn outreach.

## Context

After a company passes validation, the next step is identifying who to reach out to. The ideal contact is someone who either makes or influences hiring decisions for AI/ML engineering roles. The closer the connection degree, the better.

**H1B Context:** Adithya is on an F1 visa requiring H1B sponsorship. Companies are sourced via three-tier H1B system: Tier 3 (startup portals: YC, Wellfound, etc.) = no H1B filter applied; Tier 1/2 (LinkedIn + general portals) = cross-checked on Frog Hire (primary) → H1BGrader/MyVisaJobs. When researching contacts, look for signals the company sponsors visas (listed on Frog Hire, international employees, "visa sponsorship" on job posts).

## Search Priority (who to find, in order)

1. **VP/Director of Engineering or CTO** — Decision makers. Best for direct outreach.
2. **Engineering Manager (AI/ML team)** — Team-level hiring authority. Often more responsive than C-level.
3. **Technical Recruiter** — Gatekeepers. Good for getting your resume into the system.
4. **Founder/CEO** — Only for companies < 50 employees where founders still hire directly.
5. **Senior AI/ML Engineer** — Peer referrals. Useful if no leadership contacts are accessible.

## Search Process

### Step 1: LinkedIn Search
Use Claude in Chrome to search LinkedIn for people at the target company.

Search queries to try (in order):
1. `[Company Name] CTO` or `[Company Name] VP Engineering`
2. `[Company Name] Engineering Manager AI`
3. `[Company Name] Technical Recruiter`
4. `[Company Name] Founder`

For each search:
- Note the LinkedIn degree (1st, 2nd, 3rd+) — this is critical for outreach strategy
- Check if there are mutual connections (2nd degree contacts)
- Note follower count (higher = more active on LinkedIn = better for pre-engagement)

### Step 2: Profile Intel
For each contact found, gather:

1. **Name and Title** — Exact current title
2. **LinkedIn Degree** — 1st (warm), 2nd (reachable), 3rd+ (cold)
3. **Follower Count** — Indicates LinkedIn activity level
4. **Mutual Connections** — Name any relevant mutuals
5. **Recent Posts** (last 2-3) — Topic, date, engagement level. These are pre-engagement targets.
6. **Background** — Previous companies, education (look for shared alma maters or employers)
7. **Communication Style** — Formal/casual/technical, based on their posts and headline

### Step 3: Rank Contacts

Rank the contacts found by outreach priority:

**Priority Formula:**
- 1st degree → +3 points
- 2nd degree → +2 points
- 3rd+ degree → +0 points
- Decision maker (CTO/VP) → +2 points
- Recruiter → +1 point
- High follower count (>1000) → +1 point (good for pre-engagement)
- Recent posts available → +1 point (enables pre-engagement)
- Shared background (same school/company) → +1 point

## Output Format

```markdown
# Hiring Contacts: [Company Name]

## Top Contact
**[Name]** — [Title]
- LinkedIn Degree: [1st/2nd/3rd+]
- Followers: [count]
- Mutual Connections: [names or "none"]
- Priority Score: [X/10]

### Recent Activity
- [Date]: "[Post topic/summary]" — [X likes, Y comments]
- [Date]: "[Post topic/summary]" — [X likes, Y comments]

### Background
- Previous: [Key previous roles]
- Education: [School — note if shared with Adithya]

### Communication Style
[Formal/Casual/Technical] — based on [evidence from posts]

---

## Other Contacts Found
| Name | Title | Degree | Followers | Priority |
|------|-------|--------|-----------|----------|
| ... | ... | ... | ... | X/10 |

## Recommended Outreach Strategy
- **Primary target:** [Name] — [why]
- **Approach:** [Pre-engage on post about X → Connect with Y angle → Follow up with Z]
- **Timeline:** [Suggested dates, Tue-Thu]
- **Backup:** If [Name] doesn't respond, try [Backup Name]

## Next Steps
- [ ] Pre-engage on [Name]'s post about [topic]
- [ ] Draft outreach (use outreach-drafter skill)
- [ ] Update Notion CRM with contact details
```

## Where to Save

- Save to `/mnt/lineked outreach/[Company]_Contacts.md` or append to existing `[Company]_Outreach.md`
- Update Notion "LinkedIn Contacts" database with: Name, Company, Title, Degree, Followers, Connection Status, LinkedIn URL

## Edge Cases

- **No leadership found on LinkedIn:** Check the company website's "Team" or "About" page. Some startups don't have strong LinkedIn presence but list their team on their site.
- **All contacts are 3rd+:** Note this as a challenge. Recommend: (a) Apply directly on the portal first, (b) Look for alumni connections at shared schools/companies, (c) Consider InMail.
- **Very small company (<20):** The founder IS the hiring manager. Focus there.
- **Generic company name (e.g., "Clicks"):** Use more specific searches like "[Company] [City] [Product]" to avoid false matches.
