export const STATUS = {
  draft: { label: "Draft - unfunded", tone: "grey" },
  funded: { label: "Funded - held", tone: "blue" },
  submitted: { label: "Submitted", tone: "violet" },
  revision_requested: { label: "Revision requested", tone: "amber" },
  awaiting_approval: { label: "Verified - awaiting approval", tone: "teal" },
  released: { label: "Released - paying out", tone: "green" },
  paid_out: { label: "Paid out", tone: "green" },
  payout_failed: { label: "Payout failed", tone: "red" },
  voided: { label: "Cancelled", tone: "grey" },
};

export default function StatusPill({ status }) {
  const s = STATUS[status] || { label: status, tone: "grey" };
  return <span className={`pill pill-${s.tone}`}>{s.label}</span>;
}
