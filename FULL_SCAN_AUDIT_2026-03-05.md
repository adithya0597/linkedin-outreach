# FULL SCAN AUDIT — 2026-03-05
> **Purpose:** Complete transparency on what was scanned, what was found, what was kept, and what was skipped — for user verification.

---

## 1. PORTALS SCANNED (13 total)

| # | Portal | Tier | URL | Scan Status | Date(s) Scanned | Keywords/Filters Used |
|---|--------|------|-----|-------------|-----------------|----------------------|
| 1 | Work at a Startup (YC) | 3 | workatastartup.com | ✅ Scanned twice | 03/04, 03/05 | AI Engineer, Software Engineer — filtered to YC batch companies |
| 2 | Wellfound (AngelList) | 3 | wellfound.com | ✅ Scanned 03/04, ⚠️ Blocked AM 03/05, ✅ Rescanned PM 03/05 | 03/04, 03/05 PM | "AI Engineer" role filter |
| 3 | startup.jobs | 3 | startup.jobs | ✅ Scanned twice | 03/04, 03/05 | AI Engineer, ML Engineer, remote + US |
| 4 | Hiring Cafe | 3 | hiring.cafe | ✅ Scanned | 03/05 | AI Engineer keyword search |
| 5 | Top Startups | 3 | topstartups.io | ✅ Scanned | 03/05 | "AI engineer" role filter, funded startups |
| 6 | Frog Hire | 2* | froghire.ai | ✅ Reclassified | 03/05 | **Not a job portal** — H1B verification tool only |
| 7 | JobBoard AI | 2 | jobboardai.io | ✅ Scanned | 03/05 | AI Engineer search |
| 8 | AI Jobs | 2 | aijobs.ai | ✅ Scanned | 03/05 | "AI Engineer", "ML Engineer" |
| 9 | Welcome to the Jungle | 2 | welcometothejungle.com | ❌ DOWN (500 error PM) | 03/05 AM ✅, PM ❌ | "AI engineer", US filter, full-time |
| 10 | Built In | 2 | builtin.com | ✅ Scanned | 03/05 | "AI Engineer" + AI/ML category filter |
| 11 | TrueUp | 2 | trueup.io | ✅ Scanned | 03/05 | "AI Engineer" title search |
| 12 | Jobright AI | 2 | jobright.ai | ✅ Scanned | 03/05 | AI Engineer recommendations (personalized) |
| 13 | LinkedIn | 1 | linkedin.com/jobs | ✅ Deep Scan + Normal Search | 03/05 | 8 keyword searches + Premium collections (see Section 3) |

---

## 2. LINKEDIN SEARCH DETAIL — All Keywords + Result Counts

### Normal Job Search (Past 24 hours, United States, Most Recent)

| # | Keyword | Results Found | Companies Seen (Top ~5-10) | Qualifying Startups | Why Skipped |
|---|---------|:------------:|---------------------------|:-------------------:|-------------|
| 1 | "AI engineer" | 1000+ | Goldman Sachs, Capital One, Meta, Google, staffing firms | **0** | All FAANG/big tech/staffing |
| 2 | "founding engineer" AI | 5 | Virio, 2-3 staffing firms | **1** (Virio — already in list) | Best keyword. Virio was only qualifying result. |
| 3 | "LLM engineer startup" | 3 | Skyrocket Ventures, staffing firms | **0** | All staffing/Easy Apply |
| 4 | "AI engineer startup" | 3 | Dice (staffing), Skyrocket Ventures (Easy Apply), Andiamo (Data Eng, Easy Apply) | **0** | Dice = staffing; Skyrocket = Easy Apply; Andiamo = Data Engineer + Easy Apply |
| 5 | "GenAI engineer" | 1000+ | Vercel ($180-260K NYC), Esri (Redlands CA, Easy Apply), Raytheon (Richardson TX), SGA Inc (staffing, Easy Apply), Intellectt Inc (staffing) | **0** | Vercel = not AI-native; Esri = big company + Easy Apply; Raytheon = defense giant; SGA/Intellectt = staffing |
| 6 | "ML engineer startup" | 5 | Welltower (NYSE), Skyrocket Ventures x2 (Easy Apply), Andiamo x2 (Easy Apply) | **0** | Welltower = NYSE-listed; rest = staffing/Easy Apply |
| 7 | "RAG engineer" | 1000+ | Palo Alto Networks (big), Vercel ($180-280K), Kforce (staffing, Easy Apply), Dialpad ($119-151K), Stability AI (Remote), Apexsync (Easy Apply), Ciliandry (Easy Apply) | **0** | Palo Alto = big; Kforce = staffing; Stability AI = layoffs/too large; rest = Easy Apply/big |
| 8 | "Knowledge Graph engineer" | 1000+ | Lucas James Talent Partners (staffing, Easy Apply), Palo Alto Networks (big), CareSource (Remote), FIRST (NYC), Sandia National Labs (gov lab) | **0** | Lucas James = staffing; Palo Alto/Sandia = big/gov; CareSource = large managed care org |

### LinkedIn Premium Scans

| # | Premium Feature | Results | Qualifying Leads | Details |
|---|----------------|:-------:|:----------------:|---------|
| P1 | Top Applicant Collection | 243 | 1 (Peregrine) | Dominated by Easy Apply + staffing (IDR, PTR Global, Galent, BayOne, Insight Global). Only Peregrine ($130-250K NYC) was non-Easy Apply startup. |
| P2 | Top US Startups Collection | 56 | 10 (from prior deep scan) | Cohere Health, Truveta, Pinecone, Scribe, Glean — already added from earlier session |
| P3 | Actively Hiring Filter | 700+ | 0 | Same pattern as Top Applicant — staffing and Easy Apply dominant |
| P4 | Who Viewed Profile | ~12 viewers | 2 warm leads | Stealth AI Founder (anonymous, 16h ago), Charan S. (LLM/RAG engineer, 2nd degree, 44 mutual) |
| P5 | "founding engineer" AI | 47 | ~8 (from prior scan) | Virio, Muro AI, MangoDesk, etc. — already added from earlier deep scan session |

---

## 3. ALL COMPANIES FOUND — KEPT vs SKIPPED

### ✅ KEPT — 100 Companies in Target List

| # | Company | Source | Role | Why Kept |
|---|---------|--------|------|----------|
| 1 | Snorkel AI | Research + LinkedIn | Data-centric AI | Series C, <300 emp, AI-core, H1B confirmed |
| 2 | LlamaIndex | Research + LinkedIn | RAG framework | Series A, ~40 emp, DIRECT match (Graph RAG + Neo4j), H1B confirmed |
| 3 | LangChain | Research + LinkedIn | LLM framework | Series B, ~125 emp, uses LangChain in production |
| 4 | Together AI | Research | Model inference cloud | Series B, ~125 emp, ML infra match |
| 5 | Fireworks AI | Research | GPU inference | Series C, ~150 emp, MLOps match |
| 6 | Harvey AI | Research | Legal AI | Series F (but <500 emp), NLP + RAG match |
| 7 | Hippocratic AI | Research + Jobright | Healthcare AI | Series C, ~150 emp, healthcare CDC match, H1B confirmed |
| 8 | Ambience Healthcare | Research | Healthcare AI OS | Series C, ~150 emp, healthcare domain match |
| 9 | Deepgram | Research | Speech AI | Series C, ~150 emp, NLP + FastAPI match |
| 10 | Perplexity AI | Research | AI search | Series D (but <500 emp), RAG/search overlap |
| 11 | Runway | Research | AI video | Series E (but <500 emp), ML infra match |
| 12 | Cursor (Anysphere) | Research | AI code editor | Series D, code translation + AST match, H1B confirmed |
| 13-20 | 8 Startup Recruiters | LinkedIn People Search | Various | 2nd degree connections, startup-focused recruiters |
| 21 | ~~Hypercubic~~ | YC | Code migration AI | ❌ REMOVED — does not sponsor H1B |
| 22 | Pair Team | Wellfound + startup.jobs | Healthcare AI | AI Eng $240-260K, healthcare fit, H1B confirmed |
| 23 | Cinder | Wellfound | Trust & safety AI | AI Eng $200-250K, H1B confirmed |
| 24 | Clicks | YC (F25) | Computer use agents | Agentic AI match |
| 25 | Remy | startup.jobs | Founding ML Eng | Early stage, founding role |
| 26 | Fredy C. | LinkedIn | AI recruiter (Dallas!) | Local recruiter, 2nd degree |
| 27-36 | 10a Labs, Doctronic, Monstro, OpusClip, Everlaw, Hiya, Fastino, Distyl AI, Hex, Liberate | Hiring Cafe | Various AI roles | All passed initial AI-native + startup size filter. Need validation. |
| 37-40 | Rilla, AssemblyAI, Fieldguide, Kumo | Top Startups | Various AI roles | All startup-sized, AI-core. Kumo = Graph ML (strong match!) |
| 41-47 | True Anomaly, Kodiak Robotics, Pearl Health, Arize AI, Formic, Monarch, Inworld AI | TrueUp | Various | Passed size + AI-native filter. Need H1B cross-check. |
| 48-59 | NeuBird, You.com, Augment Code, Comulate, Reevo, Qualified Health, Arcade, Observe.AI, DataVisor, Develop Health, Optimal Dynamics, Zanskar | Jobright AI | Various (H1B flagged ✅) | All had H1B sponsorship flag on Jobright. Startup-sized + AI-core. |
| 60 | Benchstack AI | LinkedIn Jobs | ML Engineer | $150-180K, Mountain View, H1B noted |
| 61-68 | Clicks (rescan), Floot, EffiGov, Sixtyfour, Idler, Lightberry, MorphoAI, AgentMail | YC (rescan) | Various | YC batch companies, all <10 emp, AI-related |
| 69-72 | Besty AI, Kata.ai, Prosper AI, Sherlock | startup.jobs (rescan) | Various | Startup portal finds, need validation |
| 73 | Cohere Health | LinkedIn Premium | Healthcare AI | ~400 emp, Series C, healthcare AI — STRONG match |
| 74 | Truveta | LinkedIn Premium | Healthcare LLM | ~350 emp, Series D, healthcare + LLM |
| 75 | Muro AI | LinkedIn Jobs | Founding Engineer AI | ~15 emp, Seed, $175-250K |
| 76 | Pinecone | LinkedIn Premium | Vector DB | ~300 emp, Series B, vector search match |
| 77 | Vikara AI | LinkedIn Jobs | AI Engineer | ~20 emp, Seed |
| 78 | MangoDesk (YC S25) | LinkedIn Jobs | Founding Engineer | ~5 emp, Seed, $100-200K |
| 79 | Virio | LinkedIn Jobs | Founding Engineer | 1-10 emp, Seed, $250-500K, H1B CONFIRMED |
| 80 | Moda | LinkedIn Jobs | Founding Engineer | ~10 emp, Seed, Remote |
| 81 | Scribe | LinkedIn Premium | Sr Backend Eng | ~250 emp, Series B |
| 82 | Glean | LinkedIn Premium | Solutions Engineer | ~800 emp, Series D, $110-235K |
| 83-89 | Flint, Komodo Health, Improvado, Responsiv, Medpage, AHEAD, Cedar | Tier 3 portals (rescan) | AI Engineer | Tier 3 = no H1B filter. Need validation. |
| 90-95 | Quest AI, Pocket, Assured, Ando Tech, Elion, Netomi | Wellfound (PM rescan) | AI Engineer | Wellfound newly accessible. Need validation. |
| 96 | Norm AI | Jobright AI (rescan) | AI Engineer | $190-250K NYC, 11-50 emp, H1B CONFIRMED |
| 97 | EvenUp | Jobright AI (rescan) | AI Engineer | SF, 251-500 emp, H1B CONFIRMED |
| 98 | WITHIN | Jobright AI (rescan) | AI Engineer | LA, H1B likely |
| 99 | Peregrine | LinkedIn Top Applicant | Sr SWE AI | $130-250K NYC, H1B unknown |
| 100 | Spherecast (YC) | Web search | Founding LLM Eng | SF, YC batch, AI supply chain |

### ❌ SKIPPED — Companies Seen But NOT Added (with reasons)

#### From LinkedIn Normal Job Search (Skipped ~50+ companies)

| Company | Keyword | Salary | Why Skipped |
|---------|---------|--------|-------------|
| Goldman Sachs | "AI engineer" | — | FAANG/Big Finance — too large |
| Capital One | "AI engineer", Built In | — | Big bank — 10+ listings on Built In |
| Meta | "AI engineer" | — | FAANG |
| Google | "AI engineer" | — | FAANG |
| Vercel | "GenAI engineer", "RAG engineer" | $180-280K | Not AI-native (web dev platform), >1000 emp |
| Esri | "GenAI engineer" | — | Big company, Easy Apply |
| Raytheon | "GenAI engineer" | $86-165K | Defense giant, not AI-native |
| Software Guidance & Assistance (SGA) | "GenAI engineer" | $210-250K | Staffing/consulting firm |
| Intellectt Inc | "GenAI engineer" | — | Staffing firm |
| Palo Alto Networks | "RAG engineer", "KG engineer" | — | Cybersecurity giant, >10,000 emp |
| Kforce Inc | "RAG engineer" | $150-180K | Staffing firm, Easy Apply |
| Dialpad | "RAG engineer" | $119-151K | Comms company, not AI-core |
| Stability AI | "RAG engineer" | — | Massive layoffs, uncertain future, not hiring AI eng specifically |
| Apexsync Technologies | "RAG engineer" | — | Robotics simulation, Easy Apply |
| Ciliandry Anky Abadi | "RAG engineer" | — | Data Scientist role, Easy Apply |
| Lucas James Talent Partners | "KG engineer" | — | Staffing firm, Easy Apply |
| CareSource | "KG engineer" | — | Large managed care org, not AI-native |
| FIRST | "KG engineer" | — | Nonprofit (robotics competition), not AI company |
| Sandia National Labs | "KG engineer" | — | Government lab, not startup |
| Welltower | "ML engineer startup" | — | NYSE-listed REIT, not AI company |
| Skyrocket Ventures | Multiple keywords | — | Staffing/recruiting firm, Easy Apply |
| Andiamo | "AI engineer startup", "ML engineer startup" | — | Data Engineer role (not AI core), Easy Apply |
| Dice (via links) | "AI engineer startup" | — | Staffing job board aggregator |

#### From LinkedIn Premium - Top Applicant (Skipped ~240+ listings)

| Company/Type | Why Skipped |
|-------------|-------------|
| IDR Inc | Staffing firm |
| PTR Global | Staffing firm |
| Galent | Staffing firm |
| BayOne Solutions | Staffing firm |
| Insight Global | Staffing firm |
| Envision Technology | Staffing firm |
| Intelliswift | Staffing firm |
| Goldman Sachs (Dallas) | Big finance |
| Abnormal AI | Series D, 800+ employees — too large |
| ~230 other Easy Apply listings | Easy Apply = per user rules, skip |

#### From LinkedIn Premium - Actively Hiring (Skipped ~700+ listings)

| Type | Why Skipped |
|------|-------------|
| Staffing firms (majority) | Staffing/consulting disqualified |
| Easy Apply listings (majority) | Per user rules: ignore Easy Apply |
| Big tech companies | >1000 employees |

#### From Portal Scans — AI Jobs (Skipped ~10+ companies)

| Company | Why Skipped |
|---------|-------------|
| Anthropic | Too large, not startup-sized |
| Sezzle | Fintech, not AI-core |
| DataCamp | EdTech, not AI-core product |
| Capco | Consulting firm |
| DoorDash | Big tech delivery, not AI-core |
| Graphcore | UK-based chip company |
| StubHub | Ticketing platform, not AI |
| 84.51° (Kroger subsidiary) | Big enterprise subsidiary |

#### From Portal Scans — Built In (Skipped ~20+ companies)

| Company | Why Skipped |
|---------|-------------|
| Capital One (10+ listings) | Big bank |
| MassMutual | Big insurance |
| Datadog | >1000 employees |
| Samsara | >1000 employees |
| Dynatrace | >1000 employees |
| CoreWeave | >1000 employees (rapid growth) |
| Block | Big tech (Square/Cash App parent) |
| Wasabi Technologies | Cloud storage, not AI-core |

#### From Portal Scans — Welcome to the Jungle

| Result | Why Skipped |
|--------|-------------|
| AM scan: all large corps | No startup-sized AI companies found |
| PM scan: DOWN (500 error) | Portal inaccessible |

#### From Portal Scans — JobBoard AI

| Result | Why Skipped |
|--------|-------------|
| No AI Engineer listings found | Extremely low volume portal — essentially zero relevant results |

#### From LinkedIn — Prior Deep Scan (Companies seen but not added)

| Type | Why Skipped |
|------|-------------|
| ~70 results from "ML engineer" startup search | All big companies (Microsoft, Amazon, Google, ByteDance) |
| Easy Apply listings in Top Applicant | Per user rules: ignore Easy Apply |
| Pure Data Engineer roles | Per user rules: ignore pure Data Eng without AI |

---

## 4. DISQUALIFIED COMPANIES (Were in list, then removed)

| # | Company | Was Entry # | Reason Removed |
|---|---------|:-----------:|----------------|
| 1 | Hypercubic | #21 | Does NOT sponsor H1B — confirmed |
| 2 | Irina Adamchic (person) | Was outreach target | Not in United States |

---

## 5. FILTER RULES APPLIED

| Rule | Description | How Applied |
|------|-------------|-------------|
| **<1,000 employees** | Company must have fewer than 1,000 employees | Checked via LinkedIn, Crunchbase, Frog Hire |
| **Seed through Series C** | Funding stage filter (some exceptions for late-stage if <500 emp) | Perplexity Series D kept (small), Glean Series D kept (800 emp borderline) |
| **AI/ML as CORE product** | AI must be the product, not just "uses AI" | Skipped: Vercel, Welltower, CareSource, etc. |
| **USA HQ only** | Must be headquartered in the US | Skipped: Graphcore (UK), MorphoAI (London HQ?) |
| **Ignore Easy Apply** | User rule: skip Easy Apply listings on LinkedIn | ~90% of Top Applicant / Actively Hiring results skipped |
| **Ignore pure Data Engineer** | User rule: skip Data Engineer roles without AI component | Skipped: Andiamo, various Data Eng listings |
| **Ignore staffing/consulting** | No staffing firms, consulting companies, or job aggregators | Skipped: IDR, PTR Global, Kforce, SGA, Skyrocket, Dice, etc. |
| **H1B Tier 3 (startup portals)** | NO filter — add all matching companies | YC, Wellfound, startup.jobs, Hiring Cafe, Top Startups |
| **H1B Tier 2 (general portals)** | Cross-check Frog Hire. Include unless explicit "no sponsorship" | Jobright, TrueUp, AI Jobs, Built In, WTTJ, JobBoard AI |
| **H1B Tier 1 (LinkedIn)** | Same as Tier 2 | LinkedIn job search results |

---

## 6. H1B VERIFICATION STATUS — All Companies Checked

| Company | Checked On | Result | Status |
|---------|-----------|--------|:------:|
| Hippocratic AI | Frog Hire | H1B + PERM + E-Verify, 9 LCAs FY2025, 100% approval | ✅ Confirmed |
| Snorkel AI | Frog Hire | H1B + PERM + E-Verify, 47 LCAs FY2025, ranked #4833 | ✅ Confirmed |
| Cursor (Anysphere) | Frog Hire | H1B + PERM + E-Verify, 3 LCAs FY2025 | ✅ Confirmed |
| LlamaIndex | Frog Hire | H1B + PERM + E-Verify | ✅ Confirmed |
| Pair Team | Frog Hire | H1B + PERM + E-Verify | ✅ Confirmed |
| Cinder Technologies | Frog Hire | H1B + PERM + E-Verify | ✅ Confirmed |
| Virio | Frog Hire | SF, 1-10 emp, H1B + PERM + E-Verify | ✅ Confirmed |
| Norm AI | Frog Hire | NYC, 2023, 11-50 emp, H1B + PERM + E-Verify | ✅ Confirmed |
| EvenUp | Frog Hire | SF, 2019, 251-500 emp, H1B + PERM + E-Verify | ✅ Confirmed |
| WITHIN | Frog Hire | Multiple "Within" entities, most with H1B | ⚠️ Likely |
| Observe AI | Frog Hire | No results found | ❓ Unknown |
| Peregrine | Frog Hire | Multiple "Peregrine" entities, no exact NYC match | ❓ Unknown |
| Clicks (YC F25) | Not checked | Too new/small for any H1B database | ❓ Unknown |
| Hypercubic | Verified | **Explicitly does NOT sponsor** | ❌ No Sponsor |

**Not yet H1B checked (need verification):** Most Tier 3 portal finds (#27-72, #83-95) and several LinkedIn finds (#73-78, #80-82) — these are included per "include unless explicit no" rule but should be cross-checked when prioritizing applications.

---

## 7. SCAN COVERAGE GAPS / THINGS I MAY HAVE MISSED

| Potential Gap | Status | Notes |
|---------------|--------|-------|
| Welcome to the Jungle PM scan | ❌ MISSED | 500 error — user notified, awaiting response |
| LinkedIn "NLP Engineer" keyword | ❌ NOT SEARCHED | Was in system keywords but not run |
| Frog Hire for Tier 2 companies #41-59 | ❌ NOT YET DONE | TrueUp + most Jobright finds not H1B-verified yet |
| Company validation (employee count, funding, AI-native) | ❌ PENDING for ~40 companies | Entries #27-36, #41-47, #65-72, #83-95 all say "needs validation" |
| LinkedIn People search for hiring managers | ❌ NOT YET DONE | Have company list but haven't searched for contacts at most companies |
| Afternoon scan for 9 high-velocity portals | ✅ DONE | This was the PM rescan |

---

## 8. OVERALL NUMBERS

| Metric | Count |
|--------|:-----:|
| Total portals in system | 13 (12 portals + LinkedIn) |
| Portals successfully scanned (at least once) | 12 |
| Portals DOWN/inaccessible | 1 (Welcome to the Jungle PM) |
| LinkedIn keyword searches run | 8 |
| LinkedIn Premium scans run | 5 (Top Applicant, Top US Startups, Actively Hiring, Who Viewed, founding eng) |
| Total job listings reviewed (estimated) | **~3,000+** |
| Companies KEPT (in target list) | **100** (including 1 disqualified) |
| Companies SKIPPED | **~300+** (big tech, staffing, Easy Apply, non-AI, non-US) |
| H1B verifications performed | 14 |
| H1B confirmed sponsors | 9 |
| H1B likely | 1 |
| H1B unknown | 3 |
| H1B explicitly "no" | 1 (Hypercubic) |
| Companies needing validation | ~40 |

---

*This audit was compiled from: Startup_Target_List.md (100 entries), Daily_Scan_2026-03-05_Rescan.md, CLAUDE.md session logs (Sessions 7-15), and browser scan records.*

*Ready for your review. Flag anything that should be changed, re-included, or removed.*
