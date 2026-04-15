from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    APP_ENV: str = "development"  # development | test | production
    DATABASE_URL: str = "postgresql://warmpath:warmpath@localhost:5432/warmpath"
    SECURE_HEADERS: bool = False  # True in production — enables HSTS
    ANTHROPIC_API_KEY: str = ""
    AI_MOCK_MODE: bool = True
    BETA_SANDBOX_MODE: bool = True  # Relaxed limits for early beta users
    # None = auto (disabled in production, enabled elsewhere)
    MANUAL_INTRO_CREDIT_AWARD_ENABLED: bool | None = None
    REDIS_URL: str = "redis://localhost:6379/0"
    CELERY_BROKER_URL: str = "redis://localhost:6379/0"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/1"
    CSV_ASYNC_PROCESSING: bool = True
    CORS_ORIGINS: str = "http://localhost:5173"
    STRIPE_WEBHOOK_SECRET: str = ""
    CLERK_SECRET_KEY: str = ""
    CLERK_PUBLISHABLE_KEY: str = ""
    CLERK_WEBHOOK_SECRET: str = ""
    CLERK_DOMAIN: str = ""  # e.g. "your-app.clerk.accounts.dev"
    RESEND_API_KEY: str = ""
    RESEND_WEBHOOK_SECRET: str = ""
    FROM_EMAIL: str = "WarmPath <noreply@majiq.agency>"
    FRONTEND_URL: str = "http://localhost:3000"
    ENCRYPTION_KEY: str = ""  # Fernet key (44-char base64). Empty = passthrough.
    BLIND_INDEX_KEY: str = ""  # HMAC key (hex). Empty = SHA-256 fallback.
    RATE_LIMIT_CSV_UPLOADS_PER_DAY: int = 10
    RATE_LIMIT_SEARCH_RUNS_PER_DAY: int = 50
    RATE_LIMIT_CREDIT_PURCHASES_PER_DAY: int = 5
    RATE_LIMIT_CREDIT_EXPIRE_PER_DAY: int = 2
    RATE_LIMIT_INTRO_REQUESTS_PER_DAY: int = 15
    RATE_LIMIT_INTRO_APPROVALS_PER_DAY: int = 10
    RATE_LIMIT_MANUAL_INTRO_CONFIRMS_PER_DAY: int = 8
    SUNSET_MODE: bool = False
    RECOMMENDATION_CACHE_TTL_HOURS: int = 6
    RECOMMENDATION_MAX_SCAN: int = 15
    RECOMMENDATION_MAX_RESULTS: int = 8
    DASHBOARD_TRENDS_CACHE_TTL_HOURS: int = 6
    DASHBOARD_NETWORK_CACHE_TTL_HOURS: int = 1
    KEEVS_BRIEFING_CACHE_TTL_HOURS: int = 6
    AGENT_RUN_SECRET: str = ""
    CLAUDE_MODEL: str = "claude-sonnet-4-20250514"
    CLAUDE_SCORER_MODEL: str = "claude-haiku-4-5-20251001"
    # Scaling settings
    SERVICE_ROLE: str = "all"  # web | worker | beat | all
    CELERY_CONCURRENCY: int = 2
    DB_POOL_SIZE: int = 5
    DB_MAX_OVERFLOW: int = 10
    ANTHROPIC_MAX_CONCURRENT: int = 5
    GOOGLE_API_KEY: str = ""
    GOOGLE_PROJECT_ID: str = ""  # GCP project for Vertex AI
    GOOGLE_LOCATION: str = "us-central1"  # Vertex AI region
    GOOGLE_SERVICE_ACCOUNT_JSON: str = ""  # SA key JSON (enables Vertex AI)
    GOOGLE_MAX_CONCURRENT: int = 10
    OPENAI_API_KEY: str = ""
    OPENAI_MAX_CONCURRENT: int = 10
    GROQ_API_KEY: str = ""
    GROQ_MAX_CONCURRENT: int = 30
    DEEPSEEK_API_KEY: str = ""
    DEEPSEEK_MAX_CONCURRENT: int = 10
    # Pipeline v2 settings
    CSV_PIPELINE_V2: bool = False  # Feature flag: True = streaming pipeline
    CSV_CHUNK_SIZE: int = 500  # contacts per AI batch
    CSV_STREAM_TTL_SECONDS: int = 3600  # 1 hour TTL for Redis Streams
    CLEANUP_PROVIDER: str = "gemini"  # "anthropic" | "gemini"
    QUEUE_DEPTH_THRESHOLD: int = 20
    # Gemini optimization settings
    GEMINI_CACHE_ENABLED: bool = True  # Cache system prompt + reference data
    GEMINI_BATCH_THRESHOLD: int = 5000  # Contact count threshold for batch mode
    GEMINI_BATCH_POLL_INTERVAL: int = 60  # Seconds between batch status polls
    GEMINI_BATCH_MAX_POLLS: int = 120  # Max poll attempts (~2 hours)
    ADZUNA_APP_ID: str = ""
    ADZUNA_APP_KEY: str = ""
    JOBSPY_ENABLED: bool = True
    JOBSPY_SEARCH_ALL_SITES: bool = True

    # Vector search (Qdrant)
    VECTOR_SEARCH_ENABLED: bool = False
    QDRANT_URL: str = "http://localhost:6333"
    QDRANT_API_KEY: str = ""
    QDRANT_COLLECTION: str = "warmpath"
    OPENAI_EMBEDDING_MODEL: str = "text-embedding-3-small"
    OPENAI_EMBEDDING_DIMS: int = 1536

    # Unified Memory Service
    MEMORY_SERVICE_ENABLED: bool = False
    MEMORY_QDRANT_COLLECTION: str = "warmpath_memory"
    MEMORY_BM25_WEIGHT: float = 0.4
    MEMORY_VECTOR_WEIGHT: float = 0.6
    MEMORY_TEMPORAL_HALF_LIFE_DAYS: int = 90
    MEMORY_SESSION_HALF_LIFE_DAYS: int = 30
    MEMORY_MMR_LAMBDA: float = 0.7
    MEMORY_CANDIDATE_POOL: int = 50

    # Sentry error tracking
    SENTRY_DSN: str | None = None
    SENTRY_TRACES_SAMPLE_RATE: float = 0.1

    POSTHOG_API_KEY: str = ""
    POSTHOG_PROJECT_ID: str = ""
    POSTHOG_HOST: str = "https://app.posthog.com"
    # Agent runtime (LangGraph)
    AGENT_RUNTIME_ENABLED: bool = False
    AUTONOMOUS_EXECUTION_ENABLED: bool = False
    AGENT_RUNTIME_BUDGET_DAILY_USD: float = 10.0
    AGENT_RUNTIME_EVENT_COOLDOWN_SECONDS: int = 900  # 15 min dedup
    GITHUB_AGENT_WEBHOOK_SECRET: str = ""

    model_config = {"env_file": ".env", "extra": "ignore"}

    @property
    def is_production(self) -> bool:
        return self.APP_ENV.lower() == "production"

    @property
    def manual_intro_credit_award_enabled(self) -> bool:
        if self.MANUAL_INTRO_CREDIT_AWARD_ENABLED is not None:
            return self.MANUAL_INTRO_CREDIT_AWARD_ENABLED
        return not self.is_production


settings = Settings()
