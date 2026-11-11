"""SQLite persistence (SQLModel)."""
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import JSON, Column
from sqlmodel import Field, Session, SQLModel, create_engine

from .config import settings


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Milestone(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    title: str
    description: str = ""
    client_name: str
    freelancer_name: str
    freelancer_email: str
    domain: str = "steel_drawing"  # see evaluator.DOMAINS
    criteria: str = ""  # client's acceptance prompt, one requirement per line (AI-evaluated domains)
    amount: str  # decimal string, e.g. "250.00"
    currency: str = "USD"
    expected_revision: str = "A"
    checklist: list = Field(default_factory=list, sa_column=Column(JSON))
    splits: list = Field(default_factory=list, sa_column=Column(JSON))  # [{name,email,percent}]
    auto_release: bool = False
    status: str = "draft"
    paypal_order_id: Optional[str] = None
    authorization_id: Optional[str] = None
    capture_id: Optional[str] = None
    payout_batch_id: Optional[str] = None
    payout_status: Optional[str] = None
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class Deliverable(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    milestone_id: int = Field(index=True, foreign_key="milestone.id")
    filename: str
    stored_name: str
    uploaded_at: datetime = Field(default_factory=utcnow)
    score: Optional[int] = None
    passed: Optional[bool] = None
    findings: list = Field(default_factory=list, sa_column=Column(JSON))
    extracted: dict = Field(default_factory=dict, sa_column=Column(JSON))


class Event(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    milestone_id: Optional[int] = Field(default=None, index=True)
    kind: str  # status | paypal | qa | agent | webhook | error
    message: str
    data: dict = Field(default_factory=dict, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=utcnow)


settings.data_dir.mkdir(parents=True, exist_ok=True)
settings.upload_dir.mkdir(parents=True, exist_ok=True)
engine = create_engine(settings.database_url, connect_args={"check_same_thread": False})


# Columns added after the first release: (table, column, SQL type + default).
_ADDED_COLUMNS = [
    ("milestone", "domain", "VARCHAR NOT NULL DEFAULT 'steel_drawing'"),
    ("milestone", "criteria", "VARCHAR NOT NULL DEFAULT ''"),
]


def init_db() -> None:
    SQLModel.metadata.create_all(engine)
    # Tiny additive migration so existing SQLite files keep working.
    with engine.begin() as conn:
        for table, column, ddl in _ADDED_COLUMNS:
            existing = {row[1] for row in conn.exec_driver_sql(f"PRAGMA table_info({table})")}
            if column not in existing:
                conn.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")


def get_session():
    with Session(engine) as session:
        yield session
