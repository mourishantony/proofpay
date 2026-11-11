import { useEffect, useMemo, useRef, useState } from "react";
import { AgGridReact } from "ag-grid-react";
import FundPanel from "./FundPanel.jsx";
import StatusPill from "./StatusPill.jsx";
import { gridTheme } from "./MilestoneGrid.jsx";
import { api, money } from "../api.js";

const STEPS = [
  { key: "funded", label: "Funded", done: ["funded", "submitted", "revision_requested", "awaiting_approval", "released", "paid_out", "payout_failed"] },
  { key: "submitted", label: "Submitted", done: ["submitted", "revision_requested", "awaiting_approval", "released", "paid_out", "payout_failed"] },
  { key: "verified", label: "AI verified", done: ["awaiting_approval", "released", "paid_out", "payout_failed"] },
  { key: "released", label: "Captured", done: ["released", "paid_out", "payout_failed"] },
  { key: "paid", label: "Paid out", done: ["paid_out"] },
];
const CANCELLABLE = ["funded", "submitted", "revision_requested", "awaiting_approval"];
const SEV_ORDER = { critical: 0, major: 1, minor: 2 };
// Which role must act next in each status, and what the other role sees meanwhile.
const NEXT_ACTOR = {
  draft: ["client", "fund this milestone with PayPal"],
  funded: ["freelancer", "upload the deliverable"],
  revision_requested: ["freelancer", "upload a corrected version"],
  submitted: ["freelancer", "submit the deliverable for AI review"],
  awaiting_approval: ["client", "approve and release the payment"],
  released: ["client", "confirm the payout"],
  payout_failed: ["client", "retry the payout"],
};
const ROLE_NAME = { client: "Client", freelancer: "Freelancer" };

function Stepper({ status }) {
  return (
    <ol className="stepper">
      {STEPS.map((s) => (
        <li key={s.key} className={s.done.includes(status) ? "done" : ""}><span />{s.label}</li>
      ))}
    </ol>
  );
}

function ScoreRing({ score, passed }) {
  const r = 30, c = 2 * Math.PI * r;
  return (
    <svg width="76" height="76" viewBox="0 0 76 76" className="ring">
      <circle cx="38" cy="38" r={r} className="ring-bg" />
      <circle cx="38" cy="38" r={r} className={passed ? "ring-ok" : "ring-bad"}
        strokeDasharray={c} strokeDashoffset={c * (1 - score / 100)} transform="rotate(-90 38 38)" />
      <text x="38" y="43" textAnchor="middle">{score}</text>
    </svg>
  );
}

function QaReport({ deliverable, isAI }) {
  const cols = useMemo(() => [
    { field: "severity", width: 105, sort: "asc", comparator: (a, b) => SEV_ORDER[a] - SEV_ORDER[b],
      cellRenderer: (p) => <span className={`sev sev-${p.value}`}>{p.value}</span> },
    { field: "message", headerName: "Finding", flex: 2, minWidth: 220, wrapText: true, autoHeight: true },
    { field: "evidence", flex: 1.4, minWidth: 160, wrapText: true, autoHeight: true, cellClass: "muted" },
    { field: "rule", width: 130, cellClass: "mono" },
  ], []);
  if (!deliverable || deliverable.score == null) return null;
  const x = deliverable.extracted || {};
  return (
    <section className="card">
      <div className="card-head">
        <h3>{isAI ? "AI review" : "QA report"} <span className="muted small">- {deliverable.filename}</span></h3>
        <a className="small" href={`/api/deliverables/${deliverable.id}/file`} target="_blank" rel="noreferrer">Open file</a>
      </div>
      <div className="qa-summary">
        <ScoreRing score={deliverable.score} passed={deliverable.passed} />
        <div>
          <div className={`verdict ${deliverable.passed ? "ok" : "bad"}`}>{deliverable.passed ? "PASS" : "FAIL"}</div>
          {isAI ? (
            <p className="review-summary">{x.summary || "Reviewed against the client's requirements."}</p>
          ) : (
            <div className="chips">
              {["drawing_no", "revision", "date", "drawn_by", "checked_by", "scale"].map((k) => (
                <span key={k} className={`chip ${x[k] ? "" : "chip-missing"}`}>{k.replace("_", " ")}: <b>{x[k] || "missing"}</b></span>
              ))}
            </div>
          )}
        </div>
      </div>
      {isAI && x.criteria_results ? (
        <ul className="criteria">
          {x.criteria_results.map((c) => (
            <li key={c.id} className={c.met ? "met" : "unmet"}>
              <span className="mark" aria-label={c.met ? "met" : "not met"}>{c.met ? "✓" : "✗"}</span>
              <div>
                <b>{c.criterion}</b>
                <div className="muted small">{c.evidence}</div>
                {!c.met && c.fix && <div className="fix small">Fix: {c.fix}</div>}
              </div>
            </li>
          ))}
        </ul>
      ) : deliverable.findings.length ? (
        <div className="grid-wrap"><AgGridReact theme={gridTheme} rowData={deliverable.findings} columnDefs={cols} domLayout="autoHeight" /></div>
      ) : <div className="alert alert-green">No findings - all checklist items passed.</div>}
    </section>
  );
}

function Timeline({ events }) {
  const endRef = useRef(null);
  // Braces matter: newer Chromium returns a Promise from scrollIntoView, which React would treat as a cleanup.
  useEffect(() => { endRef.current?.scrollIntoView({ block: "nearest" }); }, [events.length]);
  return (
    <section className="card">
      <h3>Agent and payment audit trail</h3>
      <ul className="timeline">
        {events.map((e) => (
          <li key={e.id} className={`ev ev-${e.kind}`}>
            <div className="ev-meta"><span className="ev-kind">{e.kind}</span>{new Date(e.created_at + "Z").toLocaleTimeString()}</div>
            <div className="ev-msg">{e.message}</div>
            {e.data?.thinking && <details><summary>reasoning</summary><p className="thinking">{e.data.thinking}</p></details>}
            {e.data?.reasons && <ul className="reasons">{e.data.reasons.map((r, i) => <li key={i}>{r}</li>)}</ul>}
            {e.data?.input && Object.keys(e.data.input).length > 0 && <code className="ev-code">{JSON.stringify(e.data.input)}</code>}
          </li>
        ))}
        <li ref={endRef} />
      </ul>
    </section>
  );
}

function Uploader({ milestone, domain, onDone, onError }) {
  const [busy, setBusy] = useState(false);
  const [samples, setSamples] = useState([]);
  useEffect(() => { api.samples(milestone.domain).then(setSamples).catch(() => {}); }, [milestone.domain]);
  async function send(file) {
    setBusy(true);
    try { await api.upload(milestone.id, file); onDone(); } catch (e) { onError(e.message); } finally { setBusy(false); }
  }
  return (
    <div>
      <label className={`dropzone ${busy ? "busy" : ""}`}>
        <input type="file" accept={domain.accept.join(",")} disabled={busy} onChange={(e) => e.target.files[0] && send(e.target.files[0])} />
        <b>{busy ? "Uploading..." : "Upload your deliverable"}</b>
        <span className="muted small">{domain.ai ? domain.hint : `Shop drawing PDF for REV ${milestone.expected_revision}`}</span>
      </label>
      {samples.length > 0 && (
        <div className="samples small">
          Demo files:{" "}
          {samples.map((s) => (
            <button key={s} className="btn-link" disabled={busy} onClick={async () => send(await api.sampleFile(s))}>{s}</button>
          ))}
        </div>
      )}
    </div>
  );
}

export default function MilestoneDetail({ config, role, detail, reload, notify }) {
  const [busy, setBusy] = useState("");
  const m = detail;
  const latest = m.deliverables[0];
  const domain = config.domains[m.domain] || config.domains.other;
  const isAI = domain.ai;
  const criteria = (m.criteria || "").split(/\r?\n/).map((l) => l.trim().replace(/^[-*]\s*/, "")).filter(Boolean);

  async function act(label, fn, success) {
    setBusy(label);
    try { const r = await fn(); notify(success(r), "green"); } catch (e) { notify(e.message, "red"); } finally { setBusy(""); reload(); }
  }

  let action = null;
  switch (m.status) {
    case "draft":
      action = (<><p>Fund this milestone. PayPal <b>authorizes and holds</b> {money(m.amount, m.currency)}. Nothing is captured until the work is verified.</p>
        <FundPanel config={config} milestone={m} onFunded={() => { notify("Funds authorized and held by PayPal", "green"); reload(); }} onError={(msg) => notify(msg, "red")} /></>);
      break;
    case "funded":
    case "revision_requested":
      action = (<><p>{m.status === "revision_requested" ? "The agent requested a revision. Upload the corrected drawing." : "Funds are held by PayPal. Upload your deliverable to get paid."}</p>
        <Uploader milestone={m} domain={domain} onDone={() => { notify("Deliverable uploaded", "green"); reload(); }} onError={(msg) => notify(msg, "red")} /></>);
      break;
    case "submitted":
      action = (<><p>Submit for AI review. {isAI ? "The AI checks your work against every requirement the client wrote" : "The agent checks the drawing against the checklist"} and decides what happens to the held payment.</p>
        <button className="btn-primary btn-lg" disabled={!!busy} onClick={() => act("agent", () => api.runAgent(m.id), (r) => `Agent (${r.mode}) decision: ${r.decision?.replace("_", " ")}`)}>
          {busy === "agent" ? <><span className="spinner" /> Agent reviewing...</> : "Submit for AI review"}</button></>);
      break;
    case "awaiting_approval":
      action = (<><p>The agent verified the deliverable. Approve to <b>capture</b> the held funds and pay out the split.</p>
        <button className="btn-primary btn-lg" disabled={!!busy} onClick={() => act("approve", () => api.approve(m.id), () => "Payment captured and payout sent")}>
          {busy === "approve" ? <><span className="spinner" /> Releasing...</> : `Approve and release ${money(m.amount, m.currency)}`}</button></>);
      break;
    case "released":
      action = (<><p>Funds captured. Payout batch <code>{m.payout_batch_id}</code> is <b>{m.payout_status}</b>.</p>
        <button className="btn-secondary" disabled={!!busy} onClick={() => act("refresh", () => api.refreshPayout(m.id), (r) => `Payout status: ${r.batch_status}`)}>Refresh payout status</button></>);
      break;
    case "payout_failed":
      action = (<><p>Capture succeeded but the payout failed. Check payee emails, then retry.</p>
        <button className="btn-secondary" disabled={!!busy} onClick={() => act("retry", () => api.retryPayout(m.id), () => "Payout retried")}>Retry payout</button></>);
      break;
    case "paid_out":
      action = <div className="alert alert-green">Done. All payees were paid through PayPal Payouts.</div>;
      break;
    default:
      action = <div className="alert">This milestone was cancelled and the hold was released.</div>;
  }
  const [owner, waitFor] = NEXT_ACTOR[m.status] || [];
  if (owner && owner !== role) {
    action = (<div className="waiting">Waiting for the <b>{ROLE_NAME[owner]}</b> to {waitFor}.
      <span className="muted small">(Switch role at the top right to continue the demo.)</span></div>);
  }

  return (
    <div className="detail">
      <section className="card">
        <div className="card-head">
          <div>
            <div className="muted small">Milestone #{m.id} - {m.client_name} to {m.freelancer_name}</div>
            <h2>{m.title}</h2>
          </div>
          <div className="amount">{money(m.amount, m.currency)}</div>
        </div>
        <div className="status-row">
          <StatusPill status={m.status} />
          <span className="type-tag">{domain.label}</span>
          <span className="muted small">{isAI ? `${criteria.length} requirement${criteria.length === 1 ? "" : "s"} - client approves release` : `REV ${m.expected_revision} required - auto-release ${m.auto_release ? "on" : "off"}`}</span>
        </div>
        <Stepper status={m.status} />
        {m.description && <p className="muted small">{m.description}</p>}
        {isAI && criteria.length > 0 && (
          <details className="req-list" open={role === "freelancer"}><summary>Acceptance requirements ({criteria.length})</summary>
            <ol>{criteria.map((c, i) => <li key={i}>{c}</li>)}</ol></details>
        )}
        <div className="action">{action}</div>
        {role === "client" && CANCELLABLE.includes(m.status) && (
          <button className="btn-link danger small" disabled={!!busy}
            onClick={() => window.confirm("Cancel and release the held funds back to the client?") && act("void", () => api.void(m.id), () => "Authorization voided")}>
            Cancel milestone and void hold</button>
        )}
      </section>

      <QaReport deliverable={latest} isAI={isAI} />

      <section className="card">
        <h3>Payout split</h3>
        <table className="split">
          <tbody>
            {m.payout_preview.map((p) => (
              <tr key={p.sender_item_id}><td>{p.name || "Payee"}</td><td className="muted">{p.email}</td><td className="num">{money(p.amount, m.currency)}</td></tr>
            ))}
          </tbody>
        </table>
        <div className="muted small ids">
          {m.paypal_order_id && <span>Order <code>{m.paypal_order_id}</code></span>}
          {m.authorization_id && <span>Auth <code>{m.authorization_id}</code></span>}
          {m.capture_id && <span>Capture <code>{m.capture_id}</code></span>}
          {m.payout_batch_id && <span>Payout <code>{m.payout_batch_id}</code></span>}
        </div>
      </section>

      <Timeline events={m.events} />
    </div>
  );
}
