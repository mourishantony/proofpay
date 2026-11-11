"""ProofPay API - AI-verified milestone payments on PayPal."""
import json
import logging
from contextlib import asynccontextmanager
from decimal import Decimal, InvalidOperation
from pathlib import Path

from fastapi import Depends, FastAPI, File, Header, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, EmailStr, Field, field_validator, model_validator
from sqlmodel import Session, select

from . import agent, evaluator, qa, services
from .config import ROOT_DIR, settings
from .db import Deliverable, Event, Milestone, get_session, init_db
from .paypal import PayPalError, get_paypal

log = logging.getLogger("proofpay")
SAMPLES_DIR = ROOT_DIR / "samples"
SAMPLE_PREFIX = {"steel_drawing": "beam_", "code": "invoice_"}  # demo files per work type
FRONTEND_DIST = ROOT_DIR / "frontend" / "dist"


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    yield


app = FastAPI(title="ProofPay", version="0.1.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_methods=["*"], allow_headers=["*"])


@app.exception_handler(services.FlowError)
async def _flow_error(_: Request, exc: services.FlowError):
    return JSONResponse(status_code=409, content={"detail": str(exc)})


@app.exception_handler(PayPalError)
async def _paypal_error(_: Request, exc: PayPalError):
    log.warning("PayPal error: %s %s", exc, exc.details)
    return JSONResponse(status_code=502, content={"detail": str(exc), "paypal": exc.details})


# ---- schemas ------------------------------------------------------------------
class Split(BaseModel):
    name: str = ""
    email: EmailStr
    percent: float = Field(gt=0, le=100)


class MilestoneIn(BaseModel):
    title: str = Field(min_length=3, max_length=120)
    description: str = Field(default="", max_length=2000)
    client_name: str = Field(min_length=1, max_length=80)
    freelancer_name: str = Field(min_length=1, max_length=80)
    freelancer_email: EmailStr
    amount: str
    domain: str = "steel_drawing"
    criteria: str = Field(default="", max_length=4000)
    expected_revision: str = Field(default="A", min_length=1, max_length=3)
    checklist: list[str] = Field(default_factory=lambda: list(qa.DEFAULT_CHECKLIST))
    splits: list[Split] = Field(default_factory=list)
    auto_release: bool = False

    @model_validator(mode="after")
    def _domain_rules(self):
        if self.domain not in evaluator.DOMAINS:
            raise ValueError(f"unknown work type '{self.domain}'")
        if evaluator.is_ai_domain(self.domain):
            lines = evaluator.criteria_lines(self.criteria)
            if not lines:
                raise ValueError("add at least one acceptance requirement (one per line)")
            if len(lines) > 30:
                raise ValueError("use at most 30 requirements")
            if self.auto_release:
                raise ValueError("auto-release is only available for built-in checks; AI-evaluated work needs client approval")
        return self

    @field_validator("amount")
    @classmethod
    def _amount(cls, v: str) -> str:
        try:
            d = Decimal(v)
        except InvalidOperation:
            raise ValueError("amount must be a number")
        if d <= 0 or d > 10000:
            raise ValueError("amount must be between 0 and 10,000")
        return services.money(d)

    @field_validator("checklist")
    @classmethod
    def _checklist(cls, v: list[str]) -> list[str]:
        unknown = set(v) - set(qa.RULES)
        if unknown:
            raise ValueError(f"unknown checklist rules: {sorted(unknown)}")
        return v


class AuthorizeIn(BaseModel):
    order_id: str = Field(min_length=5, max_length=64)


# ---- roles ---------------------------------------------------------------------
# Demo role switch: the UI sends the active role in a header and the server enforces
# which actions each role may take. This is NOT authentication - add real login
# (e.g. OAuth / per-user accounts) before any production use.
ROLE_HEADER = "X-ProofPay-Role"
ROLES = {"client", "freelancer"}


def require_role(*allowed: str):
    def check(x_proofpay_role: str = Header(default="", alias=ROLE_HEADER)) -> str:
        role = x_proofpay_role.strip().lower()
        if role not in ROLES:
            raise HTTPException(401, f"Choose a role (send {ROLE_HEADER}: client or freelancer).")
        if role not in allowed:
            names = " or ".join(a.capitalize() for a in allowed)
            raise HTTPException(403, f"Only the {names} can do this.")
        return role
    return check


CLIENT = [Depends(require_role("client"))]
FREELANCER = [Depends(require_role("freelancer"))]


def _get(session: Session, milestone_id: int) -> Milestone:
    ms = session.get(Milestone, milestone_id)
    if not ms:
        raise HTTPException(404, "Milestone not found")
    return ms


def _summary(session: Session, ms: Milestone) -> dict:
    d = services.latest_deliverable(session, ms.id)
    return {**ms.model_dump(), "qa_score": d.score if d else None, "qa_passed": d.passed if d else None}


# ---- config / dashboard -------------------------------------------------------
@app.get("/api/config")
def config():
    return {"paypal_client_id": settings.paypal_client_id, "paypal_configured": settings.paypal_configured,
            "currency": settings.currency, "ai_mode": settings.effective_ai_mode, "model": settings.ai_model,
            "checklist_rules": qa.RULES, "qa_pass_score": settings.qa_pass_score,
            "domains": evaluator.DOMAINS, "ai_evaluator_ready": bool(settings.gemini_api_key)}


@app.api_route("/api/health", methods=["GET", "HEAD"])
def health():
    return {"ok": True}


@app.get("/api/stats")
def stats(session: Session = Depends(get_session)):
    rows = session.exec(select(Milestone)).all()
    def total(statuses):
        return services.money(sum((Decimal(m.amount) for m in rows if m.status in statuses), Decimal(0)))
    return {"count": len(rows),
            "held": total({"funded", "submitted", "revision_requested", "awaiting_approval"}),
            "released": total({"released", "paid_out"}),
            "needs_attention": sum(1 for m in rows if m.status in {"awaiting_approval", "payout_failed"})}


# ---- milestones -----------------------------------------------------------------
@app.get("/api/milestones")
def list_milestones(session: Session = Depends(get_session)):
    rows = session.exec(select(Milestone).order_by(Milestone.id.desc())).all()
    return [_summary(session, m) for m in rows]


@app.post("/api/milestones", status_code=201, dependencies=CLIENT)
def create_milestone(body: MilestoneIn, session: Session = Depends(get_session)):
    splits = [s.model_dump() for s in body.splits]
    services.validate_splits(splits)
    ms = Milestone(**body.model_dump(exclude={"splits", "expected_revision"}), splits=splits,
                   currency=settings.currency, expected_revision=body.expected_revision.upper())
    session.add(ms)
    session.commit()
    session.refresh(ms)
    services.log(session, ms.id, "status", f"Milestone created by {ms.client_name}: {ms.currency} {ms.amount}")
    return _summary(session, ms)


@app.get("/api/milestones/{milestone_id}")
def get_milestone(milestone_id: int, session: Session = Depends(get_session)):
    ms = _get(session, milestone_id)
    deliverables = session.exec(select(Deliverable).where(Deliverable.milestone_id == ms.id)
                                .order_by(Deliverable.id.desc())).all()
    events = session.exec(select(Event).where(Event.milestone_id == ms.id).order_by(Event.id)).all()
    return {**_summary(session, ms), "deliverables": deliverables, "events": events,
            "payout_preview": services.compute_splits(ms)}


@app.post("/api/milestones/{milestone_id}/paypal/order", dependencies=CLIENT)
def create_order(milestone_id: int, session: Session = Depends(get_session)):
    return {"id": services.create_order(session, _get(session, milestone_id))}


@app.post("/api/milestones/{milestone_id}/paypal/authorize", dependencies=CLIENT)
def authorize(milestone_id: int, body: AuthorizeIn, session: Session = Depends(get_session)):
    return {"authorization_id": services.authorize(session, _get(session, milestone_id), body.order_id)}


@app.post("/api/milestones/{milestone_id}/deliverables", status_code=201, dependencies=FREELANCER)
async def upload(milestone_id: int, file: UploadFile = File(...), session: Session = Depends(get_session)):
    ms = _get(session, milestone_id)
    content = await file.read(settings.max_upload_mb * 1024 * 1024 + 1)
    d = services.save_deliverable(session, ms, file.filename or "deliverable.pdf", content)
    return {"deliverable_id": d.id}


@app.get("/api/deliverables/{deliverable_id}/file")
def deliverable_file(deliverable_id: int, session: Session = Depends(get_session)):
    d = session.get(Deliverable, deliverable_id)
    if not d:
        raise HTTPException(404, "Deliverable not found")
    ext = Path(d.stored_name).suffix.lower()
    # Only PDFs/images open inline; everything else is plain text or a download, so uploaded
    # HTML/JS can never run in our origin.
    media = {".pdf": "application/pdf", **evaluator.IMAGE_TYPES}.get(ext)
    if media is None:
        media = "application/zip" if ext == ".zip" else "text/plain; charset=utf-8"
    return FileResponse(settings.upload_dir / d.stored_name, media_type=media, filename=d.filename,
                        content_disposition_type="attachment" if ext == ".zip" else "inline",
                        headers={"X-Content-Type-Options": "nosniff", "Content-Security-Policy": "sandbox"})


@app.post("/api/milestones/{milestone_id}/agent/run", dependencies=FREELANCER)
def run_agent(milestone_id: int, session: Session = Depends(get_session)):
    return agent.run_agent(session, _get(session, milestone_id))


@app.post("/api/milestones/{milestone_id}/approve", dependencies=CLIENT)
def approve(milestone_id: int, session: Session = Depends(get_session)):
    result = services.release(session, _get(session, milestone_id), actor="client")
    return {"capture_status": result["capture"].get("status"), "payout_batch_id": result["payout_batch_id"]}


@app.post("/api/milestones/{milestone_id}/void", dependencies=CLIENT)
def void(milestone_id: int, session: Session = Depends(get_session)):
    services.void(session, _get(session, milestone_id))
    return {"ok": True}


@app.post("/api/milestones/{milestone_id}/payout/refresh", dependencies=CLIENT)
def refresh_payout(milestone_id: int, session: Session = Depends(get_session)):
    return services.refresh_payout(session, _get(session, milestone_id))


@app.post("/api/milestones/{milestone_id}/payout/retry", dependencies=CLIENT)
def retry_payout(milestone_id: int, session: Session = Depends(get_session)):
    return services.retry_payout(session, _get(session, milestone_id))


# ---- demo samples -----------------------------------------------------------------
@app.get("/api/samples")
def list_samples(domain: str = "steel_drawing"):
    prefix = SAMPLE_PREFIX.get(domain)
    if not prefix or not SAMPLES_DIR.exists():
        return []
    accept = evaluator.DOMAINS[domain]["accept"]
    return sorted(p.name for p in SAMPLES_DIR.iterdir() if p.name.startswith(prefix) and p.suffix.lower() in accept)


@app.get("/api/samples/{name}")
def sample(name: str):
    path = (SAMPLES_DIR / name).resolve()
    if path.parent != SAMPLES_DIR.resolve() or path.suffix not in {".pdf", ".py"} or not path.exists():
        raise HTTPException(404, "Sample not found")
    media = "application/pdf" if path.suffix == ".pdf" else "text/plain; charset=utf-8"
    return FileResponse(path, media_type=media, filename=name, headers={"X-Content-Type-Options": "nosniff"})


# ---- PayPal webhooks --------------------------------------------------------------
@app.post("/api/paypal/webhook")
async def paypal_webhook(request: Request, session: Session = Depends(get_session)):
    if not settings.paypal_webhook_id:
        raise HTTPException(400, "Webhook not configured (PAYPAL_WEBHOOK_ID)")
    event = json.loads(await request.body())
    if not get_paypal().verify_webhook(dict(request.headers), event, settings.paypal_webhook_id):
        raise HTTPException(400, "Invalid webhook signature")

    etype, resource = event.get("event_type", ""), event.get("resource", {})
    ms = None
    custom = resource.get("custom_id") or ""
    if custom.startswith("milestone-") and custom[10:].isdigit():
        ms = session.get(Milestone, int(custom[10:]))
    batch_id = resource.get("batch_header", {}).get("payout_batch_id") or resource.get("payout_batch_id")
    if ms is None and batch_id:
        ms = session.exec(select(Milestone).where(Milestone.payout_batch_id == batch_id)).first()

    services.log(session, ms.id if ms else None, "webhook", f"PayPal webhook: {etype}", {"id": event.get("id")})
    # Webhooks only update informational state; they never move money.
    if ms and etype.startswith("PAYMENT.PAYOUTSBATCH."):
        services.apply_payout_status(session, ms, resource.get("batch_header", {}).get("batch_status"))
    return {"ok": True}


# ---- frontend (built SPA) -----------------------------------------------------------
if FRONTEND_DIST.exists():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets")

    @app.api_route("/{path:path}", methods=["GET", "HEAD"], include_in_schema=False)
    def spa(path: str):
        candidate = (FRONTEND_DIST / path).resolve()
        if path and candidate.is_file() and FRONTEND_DIST.resolve() in candidate.parents:
            return FileResponse(candidate)
        return FileResponse(FRONTEND_DIST / "index.html")
