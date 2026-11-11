"""End-to-end API flow with a fake PayPal client (no network, no credentials)."""
import os
import tempfile
from pathlib import Path

os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="proofpay-test-")
os.environ["AI_MODE"] = "rules"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import paypal, qa  # noqa: E402
from app.config import settings  # noqa: E402
from app.main import app  # noqa: E402

settings.ai_mode = "rules"  # .env may hold real AI keys; tests must stay offline

SAMPLES = Path(__file__).resolve().parents[2] / "samples"
CLIENT = {"X-ProofPay-Role": "client"}
FREELANCER = {"X-ProofPay-Role": "freelancer"}


class FakePayPal:
    def __init__(self):
        self.calls = []

    def create_authorize_order(self, **kw):
        self.calls.append(("order", kw))
        return {"id": "ORDER123456", "status": "CREATED"}

    def authorize_order(self, order_id):
        self.calls.append(("authorize", order_id))
        return {"status": "COMPLETED", "purchase_units": [{"payments": {"authorizations": [{"id": "AUTH999"}]}}]}

    def capture_authorization(self, auth_id, idempotency_key):
        self.calls.append(("capture", auth_id))
        return {"id": "CAP777", "status": "COMPLETED"}

    def create_payout(self, **kw):
        self.calls.append(("payout", kw))
        return {"batch_header": {"payout_batch_id": "BATCH1", "batch_status": "PENDING"}}

    def get_payout(self, batch_id):
        return {"batch_header": {"batch_status": "SUCCESS"}, "items": []}

    def void_authorization(self, auth_id):
        self.calls.append(("void", auth_id))
        return {}


@pytest.fixture()
def client():
    fake = FakePayPal()
    paypal.set_paypal(fake)
    with TestClient(app) as c:
        c.fake = fake
        yield c


def _create(c, auto_release=False):
    r = c.post("/api/milestones", headers=CLIENT, json={
        "title": "Beam B12 shop drawing", "client_name": "Acme Fabricators", "freelancer_name": "Mac",
        "freelancer_email": "mac@example.com", "amount": "250", "expected_revision": "b",
        "auto_release": auto_release,
        "splits": [{"name": "Mac", "email": "mac@example.com", "percent": 70},
                   {"name": "Checker", "email": "chk@example.com", "percent": 30}],
    })
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _fund(c, mid):
    assert c.post(f"/api/milestones/{mid}/paypal/order", headers=CLIENT).json()["id"] == "ORDER123456"
    r = c.post(f"/api/milestones/{mid}/paypal/authorize", headers=CLIENT, json={"order_id": "ORDER123456"})
    assert r.status_code == 200, r.text


def _upload(c, mid, name):
    with open(SAMPLES / name, "rb") as f:
        r = c.post(f"/api/milestones/{mid}/deliverables", headers=FREELANCER, files={"file": (name, f, "application/pdf")})
    assert r.status_code == 201, r.text


def test_qa_samples():
    fail = qa.run_checks(SAMPLES / "beam_B12_rev_A_fail.pdf", "B")
    ok = qa.run_checks(SAMPLES / "beam_B12_rev_B_pass.pdf", "B")
    assert not fail["passed"] and any(f["rule"] == "revision_match" for f in fail["findings"])
    assert ok["passed"] and ok["score"] == 100, ok["findings"]


def test_fail_then_pass_then_client_approves(client):
    mid = _create(client)
    _fund(client, mid)
    _upload(client, mid, "beam_B12_rev_A_fail.pdf")
    r = client.post(f"/api/milestones/{mid}/agent/run", headers=FREELANCER).json()
    assert r["decision"] == "revision_requested"
    assert not any(c[0] == "capture" for c in client.fake.calls)

    _upload(client, mid, "beam_B12_rev_B_pass.pdf")
    r = client.post(f"/api/milestones/{mid}/agent/run", headers=FREELANCER).json()
    assert r["decision"] == "awaiting_approval"  # auto_release off -> human approves

    r = client.post(f"/api/milestones/{mid}/approve", headers=CLIENT)
    assert r.status_code == 200, r.text
    payout = next(c[1] for c in client.fake.calls if c[0] == "payout")
    assert [i["amount"] for i in payout["items"]] == ["175.00", "75.00"]

    client.post(f"/api/milestones/{mid}/payout/refresh", headers=CLIENT)
    assert client.get(f"/api/milestones/{mid}").json()["status"] == "paid_out"


def test_agent_auto_release(client):
    mid = _create(client, auto_release=True)
    _fund(client, mid)
    _upload(client, mid, "beam_B12_rev_B_pass.pdf")
    r = client.post(f"/api/milestones/{mid}/agent/run", headers=FREELANCER).json()
    assert r["decision"] == "released" and r["status"] == "released"


def test_agent_cannot_release_failed_qa(client):
    from app import services
    from app.db import Milestone, engine
    from sqlmodel import Session

    mid = _create(client, auto_release=True)
    _fund(client, mid)
    _upload(client, mid, "beam_B12_rev_A_fail.pdf")
    with Session(engine) as s:
        ms = s.get(Milestone, mid)
        services.run_qa(s, ms)
        with pytest.raises(services.FlowError):
            services.release(s, ms, actor="agent")


def test_rejects_non_pdf_and_bad_splits(client):
    mid = _create(client)
    _fund(client, mid)
    r = client.post(f"/api/milestones/{mid}/deliverables", headers=FREELANCER, files={"file": ("x.pdf", b"hello", "application/pdf")})
    assert r.status_code == 409
    r = client.post("/api/milestones", headers=CLIENT, json={
        "title": "Bad", "client_name": "A", "freelancer_name": "B", "freelancer_email": "b@example.com",
        "amount": "10", "splits": [{"email": "b@example.com", "percent": 50}]})
    assert r.status_code == 409


def test_roles_are_enforced(client):
    mid = _create(client)
    # no role / freelancer cannot create or fund
    assert client.post(f"/api/milestones/{mid}/paypal/order").status_code == 401
    assert client.post(f"/api/milestones/{mid}/paypal/order", headers=FREELANCER).status_code == 403
    _fund(client, mid)
    # client cannot upload or run the agent
    with open(SAMPLES / "beam_B12_rev_B_pass.pdf", "rb") as f:
        r = client.post(f"/api/milestones/{mid}/deliverables", headers=CLIENT, files={"file": ("x.pdf", f, "application/pdf")})
    assert r.status_code == 403 and "Freelancer" in r.json()["detail"]
    _upload(client, mid, "beam_B12_rev_B_pass.pdf")
    assert client.post(f"/api/milestones/{mid}/agent/run", headers=CLIENT).status_code == 403
    client.post(f"/api/milestones/{mid}/agent/run", headers=FREELANCER)
    # freelancer cannot release their own payment
    r = client.post(f"/api/milestones/{mid}/approve", headers=FREELANCER)
    assert r.status_code == 403 and not any(c[0] == "capture" for c in client.fake.calls)
    # reads stay open to both
    assert client.get(f"/api/milestones/{mid}").status_code == 200
