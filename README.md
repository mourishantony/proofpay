# ProofPay - pay on verified proof

**AI-verified milestone payments on PayPal.** The client's money is held by PayPal, an AI agent checks the
deliverable against the agreed acceptance checklist, and the funds are captured and split to the team
only when the work is verified.

> Built for the PayPal AI Hackathon 2026. Runs entirely on the **PayPal sandbox**, so no real money moves.

## The problem

Freelance drafters, detailers and designers often wait weeks to be paid. The client can't quickly
verify that a deliverable meets spec (right revision, title block complete, BOM matches the drawing), so
payment stalls. Escrow tools hold money but don't check the work. Review tools check the work but don't
move money.

## The solution

| Step | What happens | PayPal API |
|---|---|---|
| 1. Fund | Client funds the milestone. PayPal **authorizes and holds** the amount. | Orders v2 (`intent=AUTHORIZE`), PayPal JS SDK buttons (PayPal, Venmo, cards) |
| 2. Submit | Freelancer uploads the deliverable PDF. | - |
| 3. Verify | The **AI review agent** runs the QA checklist and decides: request a revision, recommend approval, or (if the client allowed it) release payment. | - |
| 4. Release | Held funds are **captured**. | Payments v2 authorizations `/capture` |
| 5. Split | The net amount is paid out to every payee (e.g. 70% detailer, 30% checker). | Payouts v1 |
| 6. Track | Payout status updates through webhooks or polling; every step is logged. | Webhooks (signature-verified) |
| Cancel | Client cancels; the hold is voided and the money is never taken. | Authorizations `/void` |

### Roles

| Role | Can do |
|---|---|
| **Client** | Create milestones, fund with PayPal, approve and release, cancel (void), refresh or retry payouts |
| **Detailer** | Upload deliverables and submit them for AI review |
| Both | View the dashboard, QA reports, payout split and audit trail |

Switch roles with **Acting as: Client / Detailer** at the top right. The server enforces the rules (a Detailer can never release their own payment). For the demo, the role is chosen in the UI, which is not real authentication; production would add per-user login.

### The AI agent

- Runs on **Google Gemini** (`gemini-3.6-flash`, free API tier) or **Claude** (`claude-opus-5-5`), using function/tool calling with the same tool set. The provider is picked from whichever API key is set.
- Its tools are scoped to **one milestone**: `get_milestone`, `run_qa_check`, `request_revision`,
  `recommend_approval`, `release_payment`.
- **Money safety is enforced in code, not in the prompt.** `release_payment` refuses unless the client
  enabled auto-release **and** the deterministic QA passed. A prompt injection hidden in an uploaded PDF
  cannot release funds.
- Its reasoning summary and every tool call are shown in the audit trail.
- Without an Anthropic key, the same tools run in deterministic **rules mode**, so the demo always works.

### Deliverable QA (steel shop drawings)

- Title block complete: drawing no, revision, date, drawn by, checked by, scale.
- Revision matches the revision agreed in the milestone.
- No open items (`TBD`, `HOLD`, `TO BE CONFIRMED`).
- Bill of materials present.
- Every BOM mark is called out on the drawing, and every callout is in the BOM. ASTM spec tokens such as A325 are ignored.

## Sponsor tools

- **AG Grid** (Community): milestone ledger and QA findings grids with sorting, filtering and custom cell renderers.
- **Render**: one-click Docker deploy via [`render.yaml`](render.yaml).

## Architecture

```
React + Vite + AG Grid + PayPal JS SDK
        |  /api
FastAPI ── services (state machine) ── PayPal REST (Orders, Payments, Payouts, Webhooks)
   |            |
   |            └── QA engine (PyMuPDF, deterministic rules)
   └── Agent (Gemini or Claude tool calling) ── tools bound to one milestone
SQLite (milestones, deliverables, audit events)
```

Milestone states: `draft -> funded -> submitted -> (revision_requested -> submitted)* -> awaiting_approval -> released -> paid_out` (also `voided`, `payout_failed`).

## Run locally

Prerequisites: Python 3.11+, Node 20+, a free PayPal developer account.

### 1. PayPal sandbox setup

1. Open <https://developer.paypal.com/dashboard/applications/sandbox> and create an app.
2. Copy its **Client ID** and **Secret**.
3. Under **Testing tools > Sandbox accounts**, note:
   - one **Personal** account to pay as the client
   - one or two Personal accounts to receive payouts (freelancer, checker)
4. **Use United States sandbox accounts** (business and personal). Sandbox accounts default to your developer country; India accounts cannot make domestic payments or send Payouts, so checkout fails with `UNSUPPORTED_PAYEE`-style errors. Create the app on the US business account.

### 2. Configure

```bash
cp .env.example .env
# fill PAYPAL_CLIENT_ID, PAYPAL_CLIENT_SECRET and optionally GEMINI_API_KEY (free at https://aistudio.google.com/apikey) or ANTHROPIC_API_KEY
```

### 3. Backend

```bash
python -m venv .venv
.venv/Scripts/activate        # Windows  (macOS/Linux: source .venv/bin/activate)
pip install -r backend/requirements-dev.txt
cd backend
uvicorn app.main:app --reload --port 8000
```

### 4. Frontend (dev)

```bash
cd frontend
npm install
npm run dev                   # http://localhost:5173
```

For a single-server run, use `npm run build` and then open <http://localhost:8000>. FastAPI serves the built app.

### Tests

```bash
cd backend && pytest -q
```

The tests run the whole flow (fund, failing upload, revision, passing upload, approve, split payout) against a fake PayPal client, so they need no network access.

## Deploy to Render

1. Push this repo to GitHub.
2. In Render, go to **New > Blueprint** and select the repo. It picks up `render.yaml`.
3. Set `PAYPAL_CLIENT_ID`, `PAYPAL_CLIENT_SECRET`, `GEMINI_API_KEY` (or `ANTHROPIC_API_KEY`) and (optionally) `PAYPAL_WEBHOOK_ID`.
4. In the PayPal sandbox app, add a webhook to `https://<your-app>.onrender.com/api/paypal/webhook` for
   `PAYMENT.PAYOUTSBATCH.*`, `PAYMENT.CAPTURE.*` and `PAYMENT.AUTHORIZATION.*`. Put its ID in `PAYPAL_WEBHOOK_ID`.

The free tier sleeps when idle, so the first request takes about 30 seconds. SQLite data resets on redeploy, which is fine for a demo.

## Demo script (for judges)

1. As **Client**: **+ New milestone**, fill in the payee emails (sandbox personal accounts), then **Create**.
2. **Pay with PayPal** using the sandbox personal account. The status becomes *Funded - held*.
3. Switch to **Detailer**. Under **Demo files**, click `beam_B12_rev_A_fail.pdf`, then **Submit for AI review**. It finds the wrong revision, the missing checker,
   a TBD note and BOM mismatches, then requests a revision. **The money stays on hold.**
4. Click `beam_B12_rev_B_pass.pdf`, then **Submit for AI review**. It verifies the drawing (score 100).
5. Switch to **Client** and click **Approve and release**. PayPal captures the funds, and Payouts splits them 70/30. **Refresh payout status** shows *Paid out*.

### Test credentials

<!-- Fill before submission: sandbox buyer login for judges (SANDBOX ONLY - never real credentials) -->
- Hosted demo: <https://proofpay-g4lj.onrender.com> (free tier: first load can take ~30 s)
- Sandbox buyer: `TODO` / `TODO`

## Security notes

- Sandbox only. Secrets come from environment variables and are never committed (see `.gitignore`).
- Uploads must be PDFs (magic bytes checked), are size-limited, and are stored under random names.
- Webhooks are rejected unless the PayPal signature verifies. Webhooks never move money.
- Captures and payouts use `PayPal-Request-Id` idempotency keys.
- Payment guards are server-side state checks, not LLM decisions.

## License

[MIT](LICENSE)
