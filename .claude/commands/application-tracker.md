---
name: application-tracker
description: "**Application & Outreach Tracker**: Logs applications, tracks outreach status, updates the Notion CRM and local files, and alerts on overdue follow-ups. Use this skill whenever the user says 'log application', 'update status', 'track outreach', 'I sent a message to [person]', 'I applied to [company]', 'mark as sent', 'follow-up check', 'who needs a follow-up', 'outreach status', or when the user reports sending a connection request or application. Also trigger when the user asks 'what's pending', 'who haven't I heard from', or wants a pipeline summary."
---

# Application & Outreach Tracker

Log outreach actions, update tracking systems, and surface follow-up reminders.

## What This Skill Does

This is the bookkeeping layer of the outreach system. Every time a message is sent, an application is submitted, or a response is received, this skill updates all tracking systems so nothing falls through the cracks.

**H1B Context:** Companies are sourced using a three-tier H1B system. Tier 3 (startup portals: YC, Wellfound, startup.jobs, Hiring Cafe, topstartups.io) had no H1B filter. Tier 1/2 (LinkedIn + general portals) were cross-checked on Frog Hire (primary) → H1BGrader/MyVisaJobs (secondary) and included unless explicitly "no sponsorship." When logging applications, note the source tier and H1B status.

## Tracking Systems to Update

There are three places where outreach data lives. All three should stay in sync:

### 1. Notion CRM (Primary — Source of Truth)
Located in the "Job Application Tracker" page. Three databases:

**Applications database:**
- Company, Position, Stage (Applied → Screen → Technical → Final → Offer → Rejected), Salary Range, Employees, Funding Stage, Source Portal, Fit Score, Hiring Manager, Applied Date, Follow Up date, Notes

**LinkedIn Contacts database:**
- Name, Company, Title, LinkedIn Degree, Followers, Connection Status (Not Connected → Pending → Connected → Messaged → Replied → Interview → No Response), Outreach Stage (Pre-Engage → Connection Sent → Accepted → Follow-Up Sent → Conversation → InMail), Last Contacted, Next Follow-Up, Notes, LinkedIn URL

**Daily Portal Scan Log:**
- Scan Date, Portals Scanned, New Leads Found, New Companies, Actions Taken

### 2. CLAUDE.md — Messages Sent Log
Located at `/mnt/lineked outreach/CLAUDE.md`. Contains a quick-reference table:
```
| Date | Target | Action | Response |
```
Update this table whenever a message is sent or a response is received.

### 3. Startup_Target_List.md
Located at `/mnt/lineked outreach/Startup_Target_List.md`. Update the priority actions table and individual company entries as status changes.

## Actions This Skill Handles

### Log a Sent Message
When the user says "I sent a connection request to [Name]" or similar:

1. **Notion — LinkedIn Contacts:** Update Connection Status to "Pending", Outreach Stage to "Connection Sent", Last Contacted to today, set Next Follow-Up to today + 5 days
2. **CLAUDE.md:** Add row to Messages Sent Log
3. **Startup_Target_List.md:** Update the company's status if applicable

### Log an Application
When the user says "I applied to [Company]" or similar:

1. **Notion — Applications:** Update Stage to "Applied", set Applied Date to today, set Follow Up to today + 7 days
2. **CLAUDE.md:** Add row to Messages Sent Log
3. **Startup_Target_List.md:** Update company entry

### Log a Response
When the user says "[Name] accepted my connection" or "[Company] responded":

1. **Notion — LinkedIn Contacts:** Update Connection Status (e.g., "Connected" or "Replied"), clear Next Follow-Up or set new one
2. **Notion — Applications:** Update Stage if relevant (e.g., "Screen" if they scheduled a call)
3. **CLAUDE.md:** Update the Response column in Messages Sent Log

### Follow-Up Check
When the user says "who needs a follow-up" or "what's pending":

Query the Notion databases for:
- LinkedIn Contacts where Next Follow-Up ≤ today and Connection Status is not "No Response"
- Applications where Follow Up ≤ today and Stage is not "Rejected"

Present as a prioritized action list:

```markdown
## Follow-Ups Due Today

### Overdue (should have been sent already)
1. **Aayush Naik** (Hypercubic) — Connection sent Mar 4, no response. Follow-up was due Mar 9.
   → Action: Send follow-up message (Version A from Hypercubic_Outreach.md)

### Due Today
2. **Sakshi Palta** (Hippocratic AI) — Connected Mar 5. Follow-up due today.
   → Action: Send follow-up message

### Coming Up (next 3 days)
3. **Fredy C.** — Connection sent Mar 4. Follow-up due Mar 9.
   → Action: No action yet, just tracking
```

### Pipeline Summary
When the user asks "what's my pipeline status" or "outreach summary":

Generate a quick dashboard:

```markdown
## Pipeline Summary — [DATE]

### By Stage
- Pre-Engagement: X targets
- Connection Sent (Pending): X targets
- Connected (Awaiting Follow-Up): X targets
- In Conversation: X targets
- Applied: X companies
- Interviewing: X companies

### This Week's Activity
- Messages sent: X
- Connections accepted: X
- Responses received: X
- Applications submitted: X

### Response Rate
- Connection acceptance: X/Y (Z%)
- Message response: X/Y (Z%)

### Overdue Follow-Ups: X
[List them]

### Recommended Actions Today
1. [Most urgent action]
2. [Second priority]
3. [Third priority]
```

## Timing Rules

- **Connection request → Follow-up:** 5 days if accepted, 10 days if still pending (then move to "No Response" after 14 days)
- **Application → Follow-up check:** 7 days
- **Follow-up sent → Next follow-up:** 5-7 days
- **No response after 3 touches:** Mark as "Ghosted" and deprioritize

## Output

For logging actions: Confirm what was updated across all 3 systems.
For follow-up checks: Present the prioritized action list.
For pipeline summaries: Present the dashboard.
