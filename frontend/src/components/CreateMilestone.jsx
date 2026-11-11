import { useState } from "react";
import { api } from "../api.js";

// Demo text per work type, so a judge can create a realistic milestone in one click.
const DEMOS = {
  steel_drawing: {
    title: "Beam B12 shop drawing - Rev B",
    description: "Shop drawing for beam B12 incorporating the RFI-014 response. Must be issued as Rev B, checked, with a complete BOM.",
    freelancer_name: "Mac (detailer)", amount: "250.00",
  },
  code: {
    title: "Invoice total module (Python)",
    description: "Python function calculate_invoice_total(items, tax_rate). items is a list of {price, qty}. Return subtotal plus tax rounded to 2 decimals; raise ValueError for negative price/qty or a tax rate outside 0-1.",
    freelancer_name: "Priya (developer)", amount: "120.00",
  },
  design: {
    title: "Logo for Demo Fabricators",
    description: "Square logo, company name 'Demo Fabricators' in navy blue (#0B2A5B) and steel grey, transparent or white background.",
    freelancer_name: "Ana (designer)", amount: "80.00",
  },
  document: {
    title: "Product brochure copy",
    description: "Two-page brochure text with sections: Overview, Features, Pricing, Contact. 600-900 words.",
    freelancer_name: "Sam (writer)", amount: "60.00",
  },
  other: { title: "", description: "", freelancer_name: "", amount: "" },
};

export default function CreateMilestone({ config, onClose, onCreated }) {
  const domains = config.domains;
  const [form, setForm] = useState(() => ({
    domain: "steel_drawing", ...DEMOS.steel_drawing, client_name: "Demo Fabricators Inc.", freelancer_email: "",
    expected_revision: "B", auto_release: false, checker_email: "", checker_percent: 30,
    criteria: domains.steel_drawing.template, checklist: Object.keys(config.checklist_rules),
  }));
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const isAI = domains[form.domain].ai;
  const set = (k) => (e) => setForm({ ...form, [k]: e.target.type === "checkbox" ? e.target.checked : e.target.value });

  const pickDomain = (domain) =>
    setForm({ ...form, domain, ...DEMOS[domain], criteria: domains[domain].template, auto_release: domains[domain].ai ? false : form.auto_release });

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
          { name: "Second payee", email: form.checker_email, percent: pct },
        ]
      : [];
    try {
      const { checker_email, checker_percent, ...rest } = form;
      onCreated(await api.create({ ...rest, splits, criteria: isAI ? form.criteria : "" }));
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

        <fieldset>
          <legend>Type of work</legend>
          <div className="domain-picker">
            {Object.entries(domains).map(([key, d]) => (
              <button type="button" key={key} className={form.domain === key ? "active" : ""} aria-pressed={form.domain === key} onClick={() => pickDomain(key)}>
                <b>{d.label}</b><span>{d.ai ? "AI evaluates against your requirements" : "Built-in drawing checks"}</span>
              </button>
            ))}
          </div>
          <p className="muted small">{domains[form.domain].hint}</p>
        </fieldset>

        <label>Title<input value={form.title} onChange={set("title")} required /></label>
        <label>Brief (what you asked for)<textarea rows={2} value={form.description} onChange={set("description")} /></label>

        {isAI && (
          <label>Acceptance requirements - one per line. The AI checks every line; all must pass before payment.
            <textarea rows={6} value={form.criteria} onChange={set("criteria")} required className="mono-area" /></label>
        )}

        <div className="row2">
          <label>Client<input value={form.client_name} onChange={set("client_name")} required /></label>
          <label>Amount ({config.currency})<input value={form.amount} onChange={set("amount")} inputMode="decimal" required /></label>
        </div>
        <div className="row2">
          <label>Freelancer<input value={form.freelancer_name} onChange={set("freelancer_name")} required /></label>
          <label>Freelancer PayPal email<input type="email" value={form.freelancer_email} onChange={set("freelancer_email")} placeholder="sb-xxxx@personal.example.com" required /></label>
        </div>
        <div className="row2">
          <label>Second payee PayPal email (optional split)<input type="email" value={form.checker_email} onChange={set("checker_email")} /></label>
          <label>Second payee share %<input type="number" min={1} max={99} value={form.checker_percent} onChange={set("checker_percent")} disabled={!form.checker_email} /></label>
        </div>

        {!isAI && (
          <>
            <div className="row2">
              <label>Required revision<input value={form.expected_revision} onChange={set("expected_revision")} maxLength={3} required /></label>
              <label className="check"><input type="checkbox" checked={form.auto_release} onChange={set("auto_release")} />
                Let the agent auto-release payment when the built-in checks pass</label>
            </div>
            <fieldset>
              <legend>Drawing checklist</legend>
              {Object.entries(config.checklist_rules).map(([rule, text]) => (
                <label key={rule} className="check"><input type="checkbox" checked={form.checklist.includes(rule)} onChange={() => toggleRule(rule)} /> {text}</label>
              ))}
            </fieldset>
          </>
        )}
        {isAI && !config.ai_evaluator_ready && (
          <div className="alert alert-amber">The server has no GEMINI_API_KEY, so AI evaluation will not run until one is added.</div>
        )}

        {error && <div className="alert alert-red">{error}</div>}
        <div className="modal-actions">
          <button type="button" className="btn-ghost" onClick={onClose}>Cancel</button>
          <button className="btn-primary" disabled={busy}>{busy ? "Creating..." : "Create milestone"}</button>
        </div>
      </form>
    </div>
  );
}
