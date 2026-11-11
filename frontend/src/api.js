// Active demo role ("client" | "freelancer"), sent on every request; the server enforces it.
let currentRole = localStorage.getItem("proofpay-role") === "freelancer" ? "freelancer" : "client";
export const getRole = () => currentRole;
export function setRole(role) {
  currentRole = role;
  localStorage.setItem("proofpay-role", role);
}

async function request(path, options = {}) {
  const headers = { ...(options.headers || {}), "X-ProofPay-Role": currentRole };
  const res = await fetch(`/api${path}`, { ...options, headers });
  const body = res.headers.get("content-type")?.includes("application/json") ? await res.json() : null;
  if (!res.ok) {
    const detail = body?.detail;
    const msg = Array.isArray(detail) ? detail.map((d) => `${d.loc?.slice(-1)[0]}: ${d.msg}`).join("; ") : detail;
    throw new Error(msg || `Request failed (${res.status})`);
  }
  return body;
}

const post = (path, data) =>
  request(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: data ? JSON.stringify(data) : undefined });

export const api = {
  config: () => request("/config"),
  stats: () => request("/stats"),
  milestones: () => request("/milestones"),
  milestone: (id) => request(`/milestones/${id}`),
  create: (data) => post("/milestones", data),
  createOrder: (id) => post(`/milestones/${id}/paypal/order`),
  authorize: (id, orderId) => post(`/milestones/${id}/paypal/authorize`, { order_id: orderId }),
  upload: (id, file) => {
    const form = new FormData();
    form.append("file", file);
    return request(`/milestones/${id}/deliverables`, { method: "POST", body: form });
  },
  runAgent: (id) => post(`/milestones/${id}/agent/run`),
  approve: (id) => post(`/milestones/${id}/approve`),
  void: (id) => post(`/milestones/${id}/void`),
  refreshPayout: (id) => post(`/milestones/${id}/payout/refresh`),
  retryPayout: (id) => post(`/milestones/${id}/payout/retry`),
  samples: (domain) => request(`/samples?domain=${encodeURIComponent(domain || "steel_drawing")}`),
  sampleFile: async (name) => {
    const res = await fetch(`/api/samples/${encodeURIComponent(name)}`);
    if (!res.ok) throw new Error("Sample not found");
    const blob = await res.blob();
    return new File([blob], name, { type: name.endsWith(".pdf") ? "application/pdf" : "text/plain" });
  },
};

export const money = (v, cur = "USD") =>
  new Intl.NumberFormat("en-US", { style: "currency", currency: cur }).format(Number(v || 0));
