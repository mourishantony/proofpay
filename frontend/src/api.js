async function request(path, options = {}) {
  const res = await fetch(`/api${path}`, options);
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
  samples: () => request("/samples"),
  sampleFile: async (name) => {
    const res = await fetch(`/api/samples/${encodeURIComponent(name)}`);
    if (!res.ok) throw new Error("Sample not found");
    return new File([await res.blob()], name, { type: "application/pdf" });
  },
};

export const money = (v, cur = "USD") =>
  new Intl.NumberFormat("en-US", { style: "currency", currency: cur }).format(Number(v || 0));
