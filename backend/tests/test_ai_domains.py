"""AI-evaluated work types (code, design, documents) with a scripted evaluator - no network."""
import io
import json
import zipfile
from types import SimpleNamespace

import pytest

from app import evaluator
from tests.test_flow import CLIENT, FREELANCER, SAMPLES, _fund, client  # noqa: F401  (fixture)

CRITERIA = "Implements calculate_invoice_total\nIncludes unit tests\nNo hard-coded keys"


class FakeEvaluatorModel:
    def __init__(self, answers):
        self.answers, self.prompts = list(answers), []

    def generate_content(self, *, model, contents, config):
        self.prompts.append(contents)
        return SimpleNamespace(text=json.dumps(self.answers.pop(0)))


def _fake_evaluator(monkeypatch, answers):
    models = FakeEvaluatorModel(answers)
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(evaluator.genai, "Client", lambda **kw: SimpleNamespace(models=models))
    return models


def _all(met):
    return {"results": [{"id": i, "met": met, "evidence": "ev", "fix": "" if met else "do it"} for i in (1, 2, 3)],
            "summary": "ok" if met else "needs work"}


def _create_code(c, **extra):
    r = c.post("/api/milestones", headers=CLIENT, json={
        "title": "Invoice module", "description": "Python invoice total function", "client_name": "Acme",
        "freelancer_name": "Dev", "freelancer_email": "dev@example.com", "amount": "120",
        "domain": "code", "criteria": CRITERIA, **extra})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _upload_code(c, mid, name):
    with open(SAMPLES / name, "rb") as f:
        r = c.post(f"/api/milestones/{mid}/deliverables", headers=FREELANCER, files={"file": (name, f, "text/x-python")})
    assert r.status_code == 201, r.text


def test_code_milestone_fail_then_pass_then_paid(client, monkeypatch):  # noqa: F811
    models = _fake_evaluator(monkeypatch, [_all(False), _all(True)])
    mid = _create_code(client)
    _fund(client, mid)

    _upload_code(client, mid, "invoice_v1_fail.py")
    r = client.post(f"/api/milestones/{mid}/agent/run", headers=FREELANCER).json()
    assert r["decision"] == "revision_requested" and r["qa"]["score"] == 0
    # the deliverable text and the client's numbered requirements reach the evaluator
    sent = " ".join(p.text or "" for p in models.prompts[0][0].parts)
    assert "1. Implements calculate_invoice_total" in sent and "calculate_invoice_total(items, tax_rate)" in sent
    # payment cannot be released while the latest upload has not passed
    assert client.post(f"/api/milestones/{mid}/approve", headers=CLIENT).status_code == 409

    _upload_code(client, mid, "invoice_v2_pass.py")
    r = client.post(f"/api/milestones/{mid}/agent/run", headers=FREELANCER).json()
    assert r["decision"] == "awaiting_approval" and r["qa"]["passed"]
    assert client.post(f"/api/milestones/{mid}/approve", headers=CLIENT).status_code == 200


def test_ai_work_cannot_be_auto_released(client):  # noqa: F811
    r = client.post("/api/milestones", headers=CLIENT, json={
        "title": "Logo", "client_name": "A", "freelancer_name": "B", "freelancer_email": "b@example.com",
        "amount": "50", "domain": "design", "criteria": "Uses blue", "auto_release": True})
    assert r.status_code == 422 and "auto-release" in r.text


def test_ai_work_requires_criteria(client):  # noqa: F811
    r = client.post("/api/milestones", headers=CLIENT, json={
        "title": "Essay", "client_name": "A", "freelancer_name": "B", "freelancer_email": "b@example.com",
        "amount": "50", "domain": "document", "criteria": "   \n "})
    assert r.status_code == 422


def test_evaluator_unavailable_keeps_milestone_submitted(client, monkeypatch):  # noqa: F811
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    mid = _create_code(client)
    _fund(client, mid)
    _upload_code(client, mid, "invoice_v2_pass.py")
    r = client.post(f"/api/milestones/{mid}/agent/run", headers=FREELANCER)
    assert r.status_code == 409 and "GEMINI_API_KEY" in r.json()["detail"]
    assert client.get(f"/api/milestones/{mid}").json()["status"] == "submitted"


def test_score_is_computed_in_code():
    reqs = ["a", "b", "c"]
    # model claims nothing about #3 and sends a junk entry: #3 counts as not met
    out = evaluator.score(reqs, {"results": [{"id": 1, "met": True, "evidence": "x"},
                                            {"id": 2, "met": "yes", "evidence": "y"},
                                            {"id": "3", "met": True}], "summary": "s"})
    assert out["score"] == 33 and not out["passed"] and len(out["findings"]) == 2


@pytest.mark.parametrize("domain,name,content,ok", [
    ("code", "x.py", b"print('hi')\n", True),
    ("code", "x.exe", b"MZ...", False),
    ("code", "x.py", b"\x00\x01binary", False),
    ("design", "logo.png", b"\x89PNG\r\n\x1a\n...", True),
    ("design", "logo.png", b"not a png", False),
    ("steel_drawing", "a.py", b"print(1)", False),
    ("document", "a.pdf", b"%PDF-1.7 ...", True),
])
def test_upload_validation(domain, name, content, ok):
    if ok:
        evaluator.validate_upload(domain, name, content)
    else:
        with pytest.raises(evaluator.EvaluationError):
            evaluator.validate_upload(domain, name, content)


def test_zip_reader_skips_vendor_dirs_and_limits_size():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("src/app.py", "def f():\n    return 1\n")
        zf.writestr("node_modules/lib/index.js", "ignored()")
        zf.writestr("big.txt", "a" * (evaluator.ZIP_MAX_FILE_BYTES + 10))
        zf.writestr("logo.png", b"\x89PNG")
    text, listing = evaluator._zip_to_text(buf.getvalue())
    assert "=== FILE: src/app.py ===" in text and "ignored()" not in text
    assert "=== FILE: big.txt" not in text and "logo.png" in listing
