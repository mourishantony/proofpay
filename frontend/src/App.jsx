import { useCallback, useEffect, useState } from "react";
import MilestoneGrid from "./components/MilestoneGrid.jsx";
import MilestoneDetail from "./components/MilestoneDetail.jsx";
import CreateMilestone from "./components/CreateMilestone.jsx";
import { api, getRole, money, setRole as saveRole } from "./api.js";

export default function App() {
  const [config, setConfig] = useState(null);
  const [rows, setRows] = useState([]);
  const [stats, setStats] = useState(null);
  const [selectedId, setSelectedId] = useState(null);
  const [detail, setDetail] = useState(null);
  const [showCreate, setShowCreate] = useState(false);
  const [toast, setToast] = useState(null);
  const [loadError, setLoadError] = useState("");
  const [role, setRoleState] = useState(getRole());
  const isClient = role === "client";

  const switchRole = (r) => { saveRole(r); setRoleState(r); setShowCreate(false); notify(`Now acting as the ${r === "client" ? "Client" : "Freelancer"}`); };

  const notify = useCallback((text, tone = "blue") => {
    setToast({ text, tone, id: Date.now() });
  }, []);

  useEffect(() => {
    if (!toast) return;
    const t = setTimeout(() => setToast(null), 5000);
    return () => clearTimeout(t);
  }, [toast]);

  const reload = useCallback(async () => {
    try {
      const [list, s] = await Promise.all([api.milestones(), api.stats()]);
      setRows(list);
      setStats(s);
      if (selectedId) setDetail(await api.milestone(selectedId));
      setLoadError("");
    } catch (e) {
      setLoadError(e.message);
    }
  }, [selectedId]);

  useEffect(() => { api.config().then(setConfig).catch((e) => setLoadError(e.message)); }, []);
  useEffect(() => { reload(); }, [reload]);
  useEffect(() => {
    const t = setInterval(reload, 8000); // picks up webhook-driven payout updates
    return () => clearInterval(t);
  }, [reload]);

  if (!config) return <div className="boot">{loadError ? `Cannot reach API: ${loadError}` : "Loading ProofPay..."}</div>;

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <div className="logo">&#10003;</div>
          <div><b>ProofPay</b><span className="muted small"> - pay on verified proof</span></div>
        </div>
        <div className="topbar-right">
          <span className={`badge ${config.ai_mode !== "rules" ? "badge-ai" : ""}`}>
            Agent: {config.ai_mode === "rules" ? "rules mode" : `${config.ai_mode === "gemini" ? "Gemini" : "Claude"} (${config.model})`}</span>
          <span className="badge">PayPal sandbox</span>
          <div className="role-switch" role="group" aria-label="Acting as">
            <span className="muted small">Acting as</span>
            {["client", "freelancer"].map((r) => (
              <button key={r} className={role === r ? "active" : ""} aria-pressed={role === r} onClick={() => switchRole(r)}>
                {r === "client" ? "Client" : "Freelancer"}</button>
            ))}
          </div>
          {isClient && <button className="btn-primary" onClick={() => setShowCreate(true)}>+ New milestone</button>}
        </div>
      </header>

      {stats && (
        <div className="stats">
          <div className="stat"><span>Milestones</span><b>{stats.count}</b></div>
          <div className="stat"><span>Held in PayPal</span><b>{money(stats.held, config.currency)}</b></div>
          <div className="stat"><span>Released</span><b>{money(stats.released, config.currency)}</b></div>
          <div className="stat"><span>Needs attention</span><b>{stats.needs_attention}</b></div>
        </div>
      )}
      {loadError && <div className="alert alert-red">{loadError}</div>}

      <main className={`layout ${detail ? "with-detail" : ""}`}>
        <section>
          <MilestoneGrid rows={rows} selectedId={selectedId} onSelect={(id) => { setSelectedId(id); api.milestone(id).then(setDetail); }} />
          {!rows.length && (
            <div className="empty card">
              <h3>How it works</h3>
              <ol>
                <li>The <b>Client</b> creates a milestone for any kind of work (drawings, code, designs, documents), writes the acceptance requirements, and funds it with PayPal. Funds are <b>authorized and held</b>.</li>
                <li>The <b>Freelancer</b> uploads the work (PDF, code, .zip, image or text) and submits it for AI review.</li>
                <li>The AI checks it against every requirement, with evidence, and either asks for a revision or verifies it.</li>
                <li>When the Client approves, the funds are <b>captured</b> and split to payees with <b>PayPal Payouts</b>.</li>
              </ol>
              {isClient
                ? <button className="btn-primary" onClick={() => setShowCreate(true)}>Create the demo milestone</button>
                : <p className="muted small">Switch to <b>Client</b> (top right) to create the first milestone.</p>}
            </div>
          )}
        </section>
        {detail && <MilestoneDetail config={config} role={role} detail={detail} reload={reload} notify={notify} />}
      </main>

      {showCreate && isClient && (
        <CreateMilestone config={config} onClose={() => setShowCreate(false)}
          onCreated={(ms) => { setShowCreate(false); setSelectedId(ms.id); notify("Milestone created", "green"); }} />
      )}
      {toast && <div key={toast.id} className={`toast toast-${toast.tone}`}>{toast.text}</div>}
      <footer className="foot muted small">Sandbox demo - no real money moves. Sample drawings are fictional.</footer>
    </div>
  );
}
