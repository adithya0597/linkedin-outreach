from enum import Enum


class Tier(str, Enum):
    TIER_1 = "Tier 1 - HIGH"
    TIER_2 = "Tier 2 - STRONG"
    TIER_3 = "Tier 3 - DECENT"
    TIER_4 = "Tier 4 - PORTAL"
    TIER_5 = "Tier 5 - RESCAN"


class FundingStage(str, Enum):
    PRE_SEED = "Pre-Seed"
    SEED = "Seed"
    SERIES_A = "Series A"
    SERIES_B = "Series B"
    SERIES_C = "Series C"
    SERIES_D = "Series D"
    SERIES_E = "Series E"
    SERIES_F = "Series F"
    PUBLIC = "Public"
    UNKNOWN = "Unknown"

    @property
    def is_valid_target(self) -> bool:
        return self in {
            FundingStage.PRE_SEED,
            FundingStage.SEED,
            FundingStage.SERIES_A,
            FundingStage.SERIES_B,
            FundingStage.SERIES_C,
        }


class H1BStatus(str, Enum):
    CONFIRMED = "Confirmed"
    LIKELY = "Likely"
    UNKNOWN = "Unknown"
    EXPLICIT_NO = "Explicit No"
    NOT_APPLICABLE = "N/A"  # Tier 3 auto-pass


class PortalTier(int, Enum):
    TIER_1 = 1  # LinkedIn — H1B cross-check required
    TIER_2 = 2  # General portals — H1B cross-check required
    TIER_3 = 3  # Startup portals — no H1B filter


class OutreachStage(str, Enum):
    NOT_STARTED = "Not Started"
    PRE_ENGAGED = "Pre-Engaged"
    CONNECTION_SENT = "Connection Sent"
    CONNECTED = "Connected"
    FOLLOW_UP_SENT = "Follow-Up Sent"
    RESPONDED = "Responded"
    INTERVIEW = "Interview"
    OFFER = "Offer"
    REJECTED = "Rejected"
    ARCHIVED = "Archived"


class ValidationResult(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    BORDERLINE = "BORDERLINE"


class CompanyStage(str, Enum):
    TO_APPLY = "To apply"
    APPLIED = "Applied"
    NO_ANSWER = "No Answer"
    OFFER = "Offer"
    REJECTED = "Rejected"
    DISQUALIFIED = "Disqualified"


class SourcePortal(str, Enum):
    LINKEDIN = "LinkedIn"
    WELLFOUND = "Wellfound"
    YC = "Work at a Startup (YC)"
    STARTUP_JOBS = "startup.jobs"
    HIRING_CAFE = "Hiring Cafe"
    TOP_STARTUPS = "Top Startups"
    FROG_HIRE = "Frog Hire"
    JOBBOARD_AI = "JobBoard AI"
    AI_JOBS = "AI Jobs"
    WTTJ = "Welcome to the Jungle"
    BUILT_IN = "Built In"
    TRUEUP = "TrueUp"
    JOBRIGHT = "Jobright AI"
    WEB_SEARCH = "Web Search"
    MANUAL = "Manual"

    @property
    def tier(self) -> PortalTier:
        tier_3 = {
            SourcePortal.WELLFOUND,
            SourcePortal.YC,
            SourcePortal.STARTUP_JOBS,
            SourcePortal.HIRING_CAFE,
            SourcePortal.TOP_STARTUPS,
        }
        tier_1 = {SourcePortal.LINKEDIN}
        if self in tier_3:
            return PortalTier.TIER_3
        if self in tier_1:
            return PortalTier.TIER_1
        return PortalTier.TIER_2
