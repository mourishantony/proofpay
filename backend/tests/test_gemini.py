"""Gemini agent loop driven by scripted SDK responses (no network, no key)."""
from google.genai import types as gtypes

from app import agent
from app.config import settings
from tests.test_flow import FREELANCER, _create, _fund, _upload, client  # noqa: F401  (fixture)


def _call(name, args=None):
    return gtypes.Part(function_call=gtypes.FunctionCall(name=name, args=args or {}))


def _resp(*parts):
    return gtypes.GenerateContentResponse(candidates=[gtypes.Candidate(content=gtypes.Content(role="model", parts=list(parts)))])


class FakeModels:
    def __init__(self, script):
        self.script, self.requests = list(script), []

    def generate_content(self, *, model, contents, config):
        self.requests.append(list(contents))
        return self.script.pop(0)


def _use_fake_gemini(monkeypatch, script):
    models = FakeModels(script)
    monkeypatch.setattr(agent.genai, "Client", lambda **kw: type("C", (), {"models": models})())
    monkeypatch.setattr(settings, "ai_mode", "gemini")
    return models


def test_gemini_requests_revision(client, monkeypatch):  # noqa: F811
    mid = _create(client)
    _fund(client, mid)
    _upload(client, mid, "beam_B12_rev_A_fail.pdf")
    models = _use_fake_gemini(monkeypatch, [
        _resp(gtypes.Part(text="Checking the terms.", thought=True), _call("get_milestone"), _call("run_qa_check")),
        _resp(_call("request_revision", {"message": "Please fix and resubmit.", "reasons": ["Issue as Rev B"]})),
        _resp(gtypes.Part(text="Sent back for revision; funds remain on hold.")),
    ])
    r = client.post(f"/api/milestones/{mid}/agent/run", headers=FREELANCER).json()
    assert r["mode"] == "gemini" and r["decision"] == "revision_requested"
    assert "funds remain on hold" in r["summary"]
    # second request carries the model turn plus both tool results
    roles = [c.role for c in models.requests[1]]
    assert roles == ["user", "model", "user"] and len(models.requests[1][2].parts) == 2


def test_gemini_cannot_release_without_auto_release(client, monkeypatch):  # noqa: F811
    mid = _create(client, auto_release=False)
    _fund(client, mid)
    _upload(client, mid, "beam_B12_rev_B_pass.pdf")
    _use_fake_gemini(monkeypatch, [
        _resp(_call("run_qa_check")),
        _resp(_call("release_payment", {"justification": "looks good"})),  # model overreaches
        _resp(gtypes.Part(text="Release refused; leaving for client approval.")),
    ])
    r = client.post(f"/api/milestones/{mid}/agent/run", headers=FREELANCER).json()
    assert not any(c[0] == "capture" for c in client.fake.calls)  # guard held
    assert r["decision"] == "awaiting_approval" and r["mode"] == "gemini+rules"
