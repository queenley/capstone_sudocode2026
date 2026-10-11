import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    database_url: str = os.getenv("DATABASE_URL", "sqlite:///./telesales.db")
    redis_url: str = os.getenv("REDIS_URL", "")
    secret: str = os.getenv(
        "APP_SECRET", "local-development-secret-change-before-deploy"
    )
    encryption_key: str = os.getenv("ENCRYPTION_KEY", "")
    environment: str = os.getenv("ENVIRONMENT", "development")
    auto_migrate: bool = (
        os.getenv(
            "AUTO_MIGRATE",
            "false" if os.getenv("ENVIRONMENT") == "production" else "true",
        ).lower()
        == "true"
    )
    admin_token: str = os.getenv("ADMIN_TOKEN", "local-admin-change-me")
    agent_token: str = os.getenv("AGENT_TOKEN", "local-agent-change-me")
    seller_token: str = os.getenv("SELLER_TOKEN", "local-seller-change-me")
    developer_token: str = os.getenv("DEVELOPER_TOKEN", "local-developer-change-me")
    kafka_brokers: str = os.getenv("KAFKA_BROKERS", "")
    otp_url: str = os.getenv("OTP_DELIVERY_URL", "")
    otp_token: str = os.getenv("OTP_DELIVERY_TOKEN", "")
    qdrant_url: str = os.getenv("QDRANT_URL", "")
    qdrant_key: str = os.getenv("QDRANT_API_KEY", "")
    embedding_url: str = os.getenv("EMBEDDING_URL", "")
    embedding_key: str = os.getenv("EMBEDDING_API_KEY", "")
    embedding_model: str = os.getenv("EMBEDDING_MODEL", "")
    origins: tuple[str, ...] = tuple(
        os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",")
    )

    def validate(self):
        from urllib.parse import urlparse

        # Model providers are configured by the AI service itself
        # (apps/ai-agent-service/config/models.yaml and its provider keys).
        for endpoint in (self.otp_url, self.embedding_url):
            if (
                endpoint
                and urlparse(endpoint).scheme != "https"
                and urlparse(endpoint).hostname not in ("localhost", "127.0.0.1")
            ):
                raise ValueError("Provider endpoints require HTTPS outside loopback")
        if self.environment == "production":
            if (
                len(self.secret) < 32
                or "development" in self.secret
                or not self.encryption_key
            ):
                raise ValueError("Production requires APP_SECRET and ENCRYPTION_KEY")
            tokens = [
                self.admin_token,
                self.agent_token,
                self.seller_token,
                self.developer_token,
            ]
            if len(set(tokens)) != 4 or any(
                len(t) < 32 or t.startswith("local-") for t in tokens
            ):
                raise ValueError("Production requires distinct strong role tokens")
            if not self.redis_url:
                raise ValueError("Production requires Redis configuration")


settings = Settings()
