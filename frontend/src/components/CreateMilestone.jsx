import { useState } from "react";
import { api } from "../api.js";

const DEMO = {
  title: "Beam B12 shop drawing - Rev B",
  description: "Shop drawing for beam B12 incorporating the RFI-014 response. Must be issued as Rev B, checked, with a complete BOM.",
  client_name: "Demo Fabricators Inc.",
  freelancer_name: "Mac (detailer)",
  freelancer_email: "",
  amount: "250.00",
  expected_revision: "B",
  auto_release: false,
  checker_email: "",
  checker_percent: 30,
};

export default function CreateMilestone({ config, onClose, onCreated }) {
  const [form, setForm] = useState({ ...DEMO, checklist: Object.keys(config.checklist_rules) });
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const set = (k) => (e) => setForm({ ...form, [k]: e.target.type === "checkbox" ? e.target.checked : e.target.value });

  const toggleRule = (rule) =>
    setForm({ ...form, checklist: form.checklist.includes(rule) ? form.checklist.filter((r) => r !== rule) : [...form.checklist, rule] });

  async function submit(e) {
    e.preventDefault();
    setBusy(true);
    setError("");
    const pct = Number(form.checker_percent);
    const splits = form.checker_email
      ? [
          { name: form.freelancer_name, email: form.freelancer_email, percent: 100 - pct },
          { name: "Checker", email: form.checker_email, percent: pct },
        ]
      : [];
    try {
      const { checker_email, checker_percent, ...rest } = form;
      const ms = await api.create({ ...rest, splits });
      onCreated(ms);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <form className="modal" onClick={(e) => e.stopPropagation()} onSubmit={submit}>
        <div className="modal-head">
          <h2>New milestone</h2>
          <button type="button" className="btn-ghost" onClick={onClose} aria-label="Close">x</button>
        </div>
        <p className="muted small">Prefilled with demo data. Use your PayPal <b>sandbox personal</b> account emails as payees.</p>

        <label>Title<input value={form.title} onChange={set("title")} required /></label>
        <label>Acceptance criteria / description<textarea rows={2} value={form.description} onChange={set("description")} /></label>
        <div className="row2">
          <label>Client<input value={form.client_name} onChange={set("client_name")} required /></label>
          <label>Amount ({config.currency})<input value={form.amount} onChange={set("amount")} inputMode="decimal" required /></label>
        </div>
        <div className="row2">
          <label>Freelancer<input value={form.freelancer_name} onChange={set("freelancer_name")} required /></label>
          <label>Freelancer PayPal email<input type="email" value={form.freelancer_email} onChange={set("freelancer_email")} placeholder="sb-xxxx@personal.example.com" required /></label>
        </div>
        <div className="row2">
          <label>Checker PayPal email (optional split)<input type="email" value={form.checker_email} onChange={set("checker_email")} /></label>
          <label>Checker share %<input type="number" min={1} max={99} value={form.checker_percent} onChange={set("checker_percent")} disabled={!form.checker_email} /></label>
        </div>
        <div className="row2">
          <label>Required revision<input value={form.expected_revision} onChange={set("expected_revision")} maxLength={3} required /></label>
          <label className="check"><input type="checkbox" checked={form.auto_release} onChange={set("auto_release")} />
            Let the AI agent auto-release payment when QA passes</label>
        </div>

        <fieldset>
          <legend>QA checklist</legend>
          {Object.entries(config.checklist_rules).map(([rule, text]) => (
            <label key={rule} className="check"><input type="checkbox" checked={form.checklist.includes(rule)} onChange={() => toggleRule(rule)} /> {text}</label>
          ))}
        </fieldset>

        {error && <div className="alert alert-red">{error}</div>}
        <div className="modal-actions">
          <button type="button" className="btn-ghost" onClick={onClose}>Cancel</button>
          <button className="btn-primary" disabled={busy}>{busy ? "Creating..." : "Create milestone"}</button>
        </div>
      </form>
    </div>
  );
}
