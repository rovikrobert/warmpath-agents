from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


from app.models.user import User, ConnectorProfile  # noqa: E402, F401
from app.models.company import Company  # noqa: E402, F401
from app.models.contact import Contact, ContactCompany, CsvUpload  # noqa: E402, F401
from app.models.csv_chunk import CsvUploadChunk  # noqa: E402, F401
from app.models.search_request import SearchRequest  # noqa: E402, F401
from app.models.match_result import (  # noqa: E402, F401
    IntroMessage,
    IntroRequest,
    MatchResult,
    WarmScore,
)
from app.models.enrichment import EnrichmentCache, UserFeedback, UsageLog  # noqa: E402, F401
from app.models.job import Application, JobOpening, UserJobPreferences  # noqa: E402, F401
from app.models.marketplace import (  # noqa: E402, F401
    ConnectorReputation,
    IntroFacilitation,
    MarketplaceListing,
    NetworkHolderAvailability,
    NetworkSharingPreferences,
    RecommendationDemandSignal,
)
from app.models.credits import CreditTransaction  # noqa: E402, F401
from app.models.privacy import (  # noqa: E402, F401
    ArchivedCreditTransaction,
    ConsentRecord,
    DataRequest,
    SuppressionList,
)
from app.models.referral import ReferralCode, ReferralConversion  # noqa: E402, F401
from app.models.registry import CompanyBoard  # noqa: E402, F401
from app.models.audit import AuditLog  # noqa: E402, F401
from app.models.email_campaign import EmailCampaignLog  # noqa: E402, F401
from app.models.friendship import UserBlock, UserFriendship  # noqa: E402, F401
from app.models.coaching import CoachingSession  # noqa: E402, F401
from app.models.feed import (  # noqa: E402, F401
    ContactFreshnessSignal,
    FeedItem,
    FeedItemInteraction,
    FreshnessPropagationLog,
)
from app.models.milestone import UserMilestone  # noqa: E402, F401
from app.models.gtm import (  # noqa: E402, F401
    CompetitorProfile,
    GTMExperiment,
    PartnershipOpportunity,
    PricingBenchmark,
)
from app.models.memory import Memory  # noqa: E402, F401
