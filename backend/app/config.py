"""Runtime configuration loaded from environment variables (.env supported)."""
import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parents[2]
# .env wins over inherited shell variables so local runs use only the project's own keys.
load_dotenv(ROOT_DIR / ".env", override=True)


def _bool(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


@dataclass
class Settings:
    # PayPal (sandbox only - this project never targets live money)
    paypal_client_id: str = os.getenv("PAYPAL_CLIENT_ID", "")
    paypal_client_secret: str = os.getenv("PAYPAL_CLIENT_SECRET", "")
    paypal_base_url: str = os.getenv("PAYPAL_BASE_URL", "https://api-m.sandbox.paypal.com")
    paypal_webhook_id: str = os.getenv("PAYPAL_WEBHOOK_ID", "")
    currency: str = os.getenv("CURRENCY", "USD")
    platform_fee_percent: float = float(os.getenv("PLATFORM_FEE_PERCENT", "0"))

    # AI agent
    ai_mode: str = os.getenv("AI_MODE", "auto")  # auto | claude | gemini | rules
    claude_model: str = os.getenv("CLAUDE_MODEL", "claude-opus-5-5")
    claude_effort: str = os.getenv("CLAUDE_EFFORT", "medium")
    gemini_model: str = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
    qa_pass_score: int = int(os.getenv("QA_PASS_SCORE", "80"))

    # Storage
    data_dir: Path = Path(os.getenv("DATA_DIR", str(ROOT_DIR / "data")))
    max_upload_mb: int = int(os.getenv("MAX_UPLOAD_MB", "15"))

    cors_origins: list[str] = field(
        default_factory=lambda: [o.strip() for o in os.getenv("CORS_ORIGINS", "http://localhost:5173").split(",") if o.strip()]
    )

    @property
    def database_url(self) -> str:
        return os.getenv("DATABASE_URL", f"sqlite:///{(self.data_dir / 'proofpay.db').as_posix()}")

    @property
    def upload_dir(self) -> Path:
        return self.data_dir / "uploads"

    @property
    def paypal_configured(self) -> bool:
        return bool(self.paypal_client_id and self.paypal_client_secret)

    @property
    def effective_ai_mode(self) -> str:
        """auto: Claude if an Anthropic key is set, else Gemini if a Gemini key is set, else deterministic rules."""
        if self.ai_mode in {"claude", "gemini", "rules"}:
            return self.ai_mode
        if os.getenv("ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_AUTH_TOKEN"):
            return "claude"
        if self.gemini_api_key:
            return "gemini"
        return "rules"

    @property
    def gemini_api_key(self) -> str:
        return os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or ""

    @property
    def ai_model(self) -> str:
        return {"claude": self.claude_model, "gemini": self.gemini_model}.get(self.effective_ai_mode, "")


settings = Settings()
