"""Business logic shared by the API, the AI agent and webhooks."""
import uuid
from decimal import ROUND_DOWN, Decimal
from typing import Optional

from sqlmodel import Session, select

from . import qa
from .config import settings
from .db import Deliverable, Event, Milestone, utcnow
from .paypal import PayPalError, authorization_id_from, get_paypal

# draft -> funded -> submitted -> (revision_requested -> submitted)* -> awaiting_approval -> released -> paid_out
RELEASABLE = {"submitted", "awaiting_approval", "revision_requested"}
UPLOADABLE = {"funded", "revision_requested", "submitted"}


class FlowError(Exception):
    """A request that is not valid for the milestone's current state."""


def log(session: Session, milestone_id: Optional[int], kind: str, message: str, data: Optional[dict] = None) -> Event:
    ev = Event(milestone_id=milestone_id, kind=kind, message=message, data=data or {})
    session.add(ev)
    session.commit()
    return ev


def set_status(session: Session, ms: Milestone, status: str, note: str = "") -> None:
    old = ms.status
    ms.status = status
    ms.updated_at = utcnow()
    session.add(ms)
    session.commit()
    log(session, ms.id, "status", note or f"Status {old} -> {status}", {"from": old, "to": status})


def money(value) -> str:
    return str(Decimal(str(value)).quantize(Decimal("0.01")))


def compute_splits(ms: Milestone) -> list[dict]:
    """Split the net milestone amount by percentage; rounding remainder goes to the first payee."""
    total = Decimal(ms.amount)
    fee = (total * Decimal(str(settings.platform_fee_percent)) / 100).quantize(Decimal("0.01"), ROUND_DOWN)
    net = total - fee
    splits = ms.splits or [{"name": ms.freelancer_name, "email": ms.freelancer_email, "percent": 100}]
    out = []
    for i, s in enumerate(splits):
        amt = (net * Decimal(str(s["percent"])) / 100).quantize(Decimal("0.01"), ROUND_DOWN)
        out.append({"name": s.get("name", ""), "email": s["email"], "amount": amt, "sender_item_id": f"ms{ms.id}-{i}"})
    out[0]["amount"] += net - sum(o["amount"] for o in out)
    for o in out:
        o["amount"] = money(o["amount"])
    return out


def validate_splits(splits: list[dict]) -> None:
    if not splits:
        return
    total = sum(Decimal(str(s.get("percent", 0))) for s in splits)
    if total != 100:
        raise FlowError(f"Split percentages must total 100 (got {total}).")
    for s in splits:
        if "@" not in s.get("email", ""):
            raise FlowError(f"Invalid payout email: {s.get('email')!r}")


def latest_deliverable(session: Session, milestone_id: int) -> Optional[Deliverable]:
    return session.exec(
        select(Deliverable).where(Deliverable.milestone_id == milestone_id).order_by(Deliverable.id.desc())
    ).first()


# ---- funding ----------------------------------------------------------------
def create_order(session: Session, ms: Milestone) -> str:
    if ms.status != "draft":
        raise FlowError("Milestone is already funded.")
    order = get_paypal().create_authorize_order(
        reference_id=f"MS-{ms.id}", custom_id=f"milestone-{ms.id}",
        description=f"ProofPay milestone: {ms.title}", amount=ms.amount, currency=ms.currency,
    )
    ms.paypal_order_id = order["id"]
    session.add(ms)
    session.commit()
    log(session, ms.id, "paypal", f"Created PayPal order {order['id']} (intent AUTHORIZE)", {"order_id": order["id"]})
    return order["id"]


def authorize(session: Session, ms: Milestone, order_id: str) -> str:
    if ms.status != "draft":
        raise FlowError("Milestone is already funded.")
    if order_id != ms.paypal_order_id:
        raise FlowError("Order does not belong to this milestone.")
    result = get_paypal().authorize_order(order_id)
    auth_id = authorization_id_from(result)
    if result.get("status") != "COMPLETED" or not auth_id:
        raise FlowError(f"Authorization not completed (status {result.get('status')}).")
    ms.authorization_id = auth_id
    log(session, ms.id, "paypal", f"Funds authorized and held: {ms.currency} {ms.amount}", {"authorization_id": auth_id})
    set_status(session, ms, "funded", "Client funded the milestone - funds held (authorized, not captured)")
    return auth_id


# ---- deliverables & QA ------------------------------------------------------
def save_deliverable(session: Session, ms: Milestone, filename: str, content: bytes) -> Deliverable:
    if ms.status not in UPLOADABLE:
        raise FlowError(f"Cannot upload a deliverable while status is '{ms.status}'.")
    if not content.startswith(b"%PDF"):
        raise FlowError("Only PDF deliverables are accepted.")
    if len(content) > settings.max_upload_mb * 1024 * 1024:
        raise FlowError(f"File exceeds {settings.max_upload_mb} MB.")
    stored = f"{uuid.uuid4().hex}.pdf"
    (settings.upload_dir / stored).write_bytes(content)
    safe_name = "".join(c for c in filename if c.isalnum() or c in "._- ")[:120] or "deliverable.pdf"
    d = Deliverable(milestone_id=ms.id, filename=safe_name, stored_name=stored)
    session.add(d)
    session.commit()
    session.refresh(d)
    log(session, ms.id, "qa", f"Deliverable uploaded: {safe_name}", {"deliverable_id": d.id})
    set_status(session, ms, "submitted", "Freelancer submitted a deliverable")
    return d


def run_qa(session: Session, ms: Milestone) -> dict:
    d = latest_deliverable(session, ms.id)
    if not d:
        raise FlowError("No deliverable uploaded yet.")
    result = qa.run_checks(settings.upload_dir / d.stored_name, ms.expected_revision, ms.checklist, settings.qa_pass_score)
    d.score, d.passed = result["score"], result["passed"]
    d.findings, d.extracted = result["findings"], result["extracted"]
    session.add(d)
    session.commit()
    log(session, ms.id, "qa", f"QA score {d.score}/100 - {'PASS' if d.passed else 'FAIL'} ({len(d.findings)} findings)",
        {"deliverable_id": d.id, "score": d.score, "passed": d.passed})
    return {"deliverable_id": d.id, **result}


# ---- release / void / payouts -----------------------------------------------
def release(session: Session, ms: Milestone, actor: str, justification: str = "") -> dict:
    """Capture held funds and pay out the splits. actor: 'client' or 'agent'."""
    if ms.status not in RELEASABLE or not ms.authorization_id:
        raise FlowError(f"Cannot release payment while status is '{ms.status}'.")
    d = latest_deliverable(session, ms.id)
    if actor == "agent":
        # Hard guard enforced in code, independent of what the model says.
        if not ms.auto_release:
            raise FlowError("Auto-release is off for this milestone - client approval required.")
        if not d or not d.passed:
            raise FlowError("Latest deliverable has not passed QA - release refused.")

    pp = get_paypal()
    capture = pp.capture_authorization(ms.authorization_id, idempotency_key=f"capture-ms{ms.id}-{ms.authorization_id}")
    ms.capture_id = capture.get("id")
    log(session, ms.id, "paypal", f"Captured {ms.currency} {ms.amount} ({capture.get('status')}) by {actor}",
        {"capture_id": ms.capture_id, "status": capture.get("status"), "justification": justification})
    set_status(session, ms, "released", f"Payment released by {actor}")

    splits = compute_splits(ms)
    batch_id = f"ms{ms.id}-{uuid.uuid4().hex[:10]}"
    try:
        payout = pp.create_payout(sender_batch_id=batch_id, items=splits, currency=ms.currency,
                                  note=f"Milestone '{ms.title}' approved")
        header = payout.get("batch_header", {})
        ms.payout_batch_id = header.get("payout_batch_id")
        ms.payout_status = header.get("batch_status")
        session.add(ms)
        session.commit()
        log(session, ms.id, "paypal", f"Payout batch {ms.payout_batch_id} created for {len(splits)} payee(s)",
            {"splits": splits, "batch_status": ms.payout_status})
    except PayPalError as e:
        log(session, ms.id, "error", f"Payout failed: {e}", {"details": e.details})
        set_status(session, ms, "payout_failed", "Capture succeeded but payout failed - retry from dashboard")
    return {"capture": capture, "splits": splits, "payout_batch_id": ms.payout_batch_id}


def retry_payout(session: Session, ms: Milestone) -> dict:
    if ms.status != "payout_failed":
        raise FlowError("Nothing to retry.")
    splits = compute_splits(ms)
    batch_id = f"ms{ms.id}-{uuid.uuid4().hex[:10]}"
    payout = get_paypal().create_payout(sender_batch_id=batch_id, items=splits, currency=ms.currency,
                                        note=f"Milestone '{ms.title}' approved")
    header = payout.get("batch_header", {})
    ms.payout_batch_id, ms.payout_status = header.get("payout_batch_id"), header.get("batch_status")
    log(session, ms.id, "paypal", f"Payout batch {ms.payout_batch_id} created (retry)", {"splits": splits})
    set_status(session, ms, "released", "Payout retried")
    return {"payout_batch_id": ms.payout_batch_id}


def refresh_payout(session: Session, ms: Milestone) -> dict:
    if not ms.payout_batch_id:
        raise FlowError("No payout batch for this milestone.")
    data = get_paypal().get_payout(ms.payout_batch_id)
    status = data.get("batch_header", {}).get("batch_status")
    apply_payout_status(session, ms, status)
    return {"batch_status": status, "items": [
        {"receiver": i.get("payout_item", {}).get("receiver"), "status": i.get("transaction_status")}
        for i in data.get("items", [])
    ]}


def apply_payout_status(session: Session, ms: Milestone, status: Optional[str]) -> None:
    if not status or status == ms.payout_status:
        return
    ms.payout_status = status
    session.add(ms)
    session.commit()
    log(session, ms.id, "paypal", f"Payout batch status: {status}")
    if status == "SUCCESS" and ms.status == "released":
        set_status(session, ms, "paid_out", "All payees paid")
    elif status in {"DENIED", "CANCELED"} and ms.status == "released":
        set_status(session, ms, "payout_failed", f"Payout batch {status}")


def void(session: Session, ms: Milestone) -> None:
    if ms.status not in {"funded", "submitted", "revision_requested", "awaiting_approval"} or not ms.authorization_id:
        raise FlowError(f"Cannot cancel while status is '{ms.status}'.")
    get_paypal().void_authorization(ms.authorization_id)
    log(session, ms.id, "paypal", "Authorization voided - held funds returned to client")
    set_status(session, ms, "voided", "Milestone cancelled by client")
