---
name: outreach-drafter
description: "**LinkedIn Outreach Drafter**: Generates complete LinkedIn outreach packages (pre-engagement comments, connection requests, follow-ups, multi-touch sequences) following strict character limits and job-seeker best practices. Use this skill whenever the user says 'draft outreach', 'write connection request', 'message for [person]', 'outreach for [company]', 'write a follow-up', 'LinkedIn message', 'connection note', or wants to reach out to a hiring manager, recruiter, or engineering leader. Also trigger when the user identifies a new target and needs messaging crafted."
---

# Outreach Drafter

Generate a complete LinkedIn outreach package for a target contact, following all swarm system rules and 2026 best practices.

## Context

You are drafting LinkedIn outreach for Bala Adithya Malaraju, an AI Engineer at Infinite Computer Solutions (Irving, TX). **He is on an F1 student visa and requires H1B sponsorship.** Note: Companies are sourced using a three-tier H1B system — startup portal companies (Tier 3: YC, Wellfound, startup.jobs, Hiring Cafe, topstartups.io) were included without H1B verification, general portal/LinkedIn companies (Tier 1/2) were cross-checked on Frog Hire (primary) → H1BGrader/MyVisaJobs (secondary) and included unless explicitly "no sponsorship." His key differentiators:
- **Graph RAG:** 138-node semantic knowledge graph
- **Enterprise LLM:** 90% automated code translation across 27 microservices (mainframe → cloud)
- **Healthcare:** 300+ table CDC pipelines with 99.9% data integrity
- **Agentic AI:** 26,000+ orders processed via agentic pipeline
- **Portfolio:** https://bala-adithya-malaraju.vercel.app/

## Required Inputs

Before drafting, gather or look up:
1. **Target name and title** (e.g., "Aayush Naik, CTO at Hypercubic")
2. **Company name and what they do** (brief — what's their AI product?)
3. **LinkedIn degree** (1st, 2nd, 3rd+) — affects tone and approach
4. **Recent posts or activity** (if available — for pre-engagement)
5. **Role being targeted** (if specific job posting exists)
6. **Communication style cues** (formal vs casual, based on their posts)

If any of these are missing, check `/mnt/lineked outreach/Startup_Target_List.md` and the Notion CRM databases for existing intel. If still missing, ask the user or note what needs to be researched.

## Outreach Rules (apply to ALL messages)

1. All connection requests ≤ 300 characters (Premium limit — LinkedIn truncates beyond this)
2. No job ask in first contact — lead with value, expertise, or genuine interest
3. Pre-engage (comment on posts) before sending a connection request
4. Portfolio link ONLY in follow-ups, never in connection requests
5. Match the target's communication style (formal ↔ casual)
6. Vary sentence structure across messages — no copy-paste patterns
7. No external links in connection requests (LinkedIn algorithm penalty of -60%)
8. InMail under 400 characters for 22% higher response rate
9. Best send timing: Tue-Thu, 9-11 AM in the recipient's timezone
10. Never use: "I'd love to pick your brain", "just reaching out", "hope this finds you well"
11. Lead with a specific technical insight or observation — not flattery
12. One clear ask per message — don't stack multiple requests

## Output Format

For each target, generate the following sections:

### Step 0: Pre-Engagement (2-3 comment variants)
Write 2-3 comments for the target's recent LinkedIn posts. These should:
- Add genuine value or insight (not just "Great post!")
- Demonstrate domain expertise naturally
- Be 2-4 sentences max
- Include a question or take that invites response

Label each: Version A (Recommended), Version B, Version C
Include the post topic reference so the user knows which post to comment on.

### Step 1: Connection Request (2 variants)
- **Version A (Recommended):** The stronger option
- **Version B:** Alternative angle

Each must be ≤ 300 characters (Premium limit). Show exact character count in brackets like `[287 chars ✅]` or `[315 chars ❌ — trim needed]`.

Structure: Hook (why connecting) → Credibility signal → Soft interest

### Step 2: Follow-Up Message (2 variants, sent 3-5 days after acceptance)
- **Version A:** Technical deep-dive or value-add
- **Version B:** Lighter, conversational

These can be longer (up to 1000 chars) but shorter is better. Include portfolio link here if relevant. End with a low-commitment ask (e.g., "Would you be open to a quick chat?" not "Can I interview for this role?").

### Step 3: Multi-Touch Calendar
Map out a 14-day sequence:

```
Day 0: Pre-engagement comment on [specific post]
Day 1: Connection request (Version A)
Day 4-5: Follow-up if accepted (Version A)
Day 7: Engage with another post
Day 9-10: Deeper follow-up / share relevant content
Day 14: Final touch — direct but respectful
```

Include specific dates based on today's date and optimal send days (Tue-Thu).

### Step 4: Pre-Send Checklist
Run through and mark each:
- [ ] Character count ≤ 250 for connection request
- [ ] No job ask in first contact
- [ ] No external links in connection request
- [ ] Portfolio link only in follow-up
- [ ] Matches target's communication style
- [ ] Sentence structure varies from recent messages
- [ ] Timing: scheduled for Tue-Thu, 9-11 AM recipient time
- [ ] Technical hook is specific (not generic)

### Step 5: Direct Application (if applicable)
If a job posting exists, include:
- Direct application URL
- Key JD keywords to emphasize
- Any portal-specific notes (e.g., "Wellfound top 5% responders")

## Adapting by Contact Type

**CTO/VP Engineering:** Lead with technical depth. Reference their product architecture or a technical blog post. Show you understand their stack.

**Recruiter:** Be more direct about your background. Recruiters appreciate clear, scannable messages. Include: years of experience, key technologies, location, visa status if relevant.

**Founder/CEO:** Lead with business impact. Mention revenue, efficiency, or scale metrics. Keep it shorter — founders are time-pressed.

**1st Degree (Warm):** Skip pre-engagement. Go straight to a warm, conversational message. Reference how you know them or mutual connections.

**2nd Degree:** Mention the mutual connection if appropriate. Pre-engagement is important.

**3rd+ Degree:** Pre-engagement is critical. Build visibility before connecting. Consider InMail if the person is a high-priority target.

## File Naming

Save the output to: `/mnt/lineked outreach/[Company]_Outreach.md` (or `[Person_Name]_Outreach.md` for individual targets not tied to a specific company).

## After Drafting

Remind the user to:
1. Review and personalize before sending
2. Check the target's most recent LinkedIn activity (may have new posts since research)
3. Log the outreach in the Notion CRM when sent
