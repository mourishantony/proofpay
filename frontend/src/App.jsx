import { useCallback, useEffect, useState } from "react";
import MilestoneGrid from "./components/MilestoneGrid.jsx";
import MilestoneDetail from "./components/MilestoneDetail.jsx";
import CreateMilestone from "./components/CreateMilestone.jsx";
import { api, money } from "./api.js";

export default function App() {
  const [config, setConfig] = useState(null);
  const [rows, setRows] = useState([]);
  const [stats, setStats] = useState(null);
  const [selectedId, setSelectedId] = useState(null);
  const [detail, setDetail] = useState(null);
  const [showCreate, setShowCreate] = useState(false);
  const [toast, setToast] = useState(null);
  const [loadError, setLoadError] = useState("");

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
          <span className={`badge ${config.ai_mode === "claude" ? "badge-ai" : ""}`}>
            Agent: {config.ai_mode === "claude" ? `Claude (${config.model})` : "rules mode"}</span>
          <span className="badge">PayPal sandbox</span>
          <button className="btn-primary" onClick={() => setShowCreate(true)}>+ New milestone</button>
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
                <li>Client creates a milestone and funds it with PayPal. Funds are <b>authorized and held</b>.</li>
                <li>Freelancer uploads the deliverable (shop drawing PDF).</li>
                <li>The AI agent checks it against the acceptance checklist and requests a revision or verifies it.</li>
                <li>On approval, the funds are <b>captured</b> and split to payees with <b>PayPal Payouts</b>.</li>
              </ol>
              <button className="btn-primary" onClick={() => setShowCreate(true)}>Create the demo milestone</button>
            </div>
          )}
        </section>
        {detail && <MilestoneDetail config={config} detail={detail} reload={reload} notify={notify} />}
      </main>

      {showCreate && (
        <CreateMilestone config={config} onClose={() => setShowCreate(false)}
          onCreated={(ms) => { setShowCreate(false); setSelectedId(ms.id); notify("Milestone created", "green"); }} />
      )}
      {toast && <div key={toast.id} className={`toast toast-${toast.tone}`}>{toast.text}</div>}
      <footer className="foot muted small">Sandbox demo - no real money moves. Sample drawings are fictional.</footer>
    </div>
  );
}
