// Same-origin API client. In demo mode the tenant is chosen with X-Account-Id;
// a production deployment would exchange an SSO session for a scoped token
// server-side and never expose tenant ids to the browser.

export const session = {
  accountId: null,
};

async function request(path, options = {}) {
  const headers = { Accept: 'application/json', ...(options.headers || {}) };
  if (session.accountId !== null) headers['X-Account-Id'] = String(session.accountId);
  if (options.body) headers['Content-Type'] = 'application/json';

  const response = await fetch(path, { ...options, headers });
  const text = await response.text();
  const payload = text ? JSON.parse(text) : null;

  if (!response.ok) {
    const detail = payload && (payload.detail || payload.message);
    throw new Error(typeof detail === 'string' ? detail : `Request failed (${response.status})`);
  }
  return payload;
}

export const api = {
  accounts: () => request('/api/v1/demo/accounts'),

  overview: (asOf) => request(`/api/v1/pacing/overview?as_of=${encodeURIComponent(asOf)}`),

  alerts: (asOf) => request('/api/v1/alerts?open=true&limit=50'),

  campaign: (id, asOf) =>
    request(`/api/v1/campaigns/${id}?as_of=${encodeURIComponent(asOf)}`),

  evaluate: (asOf) =>
    request(`/api/v1/pacing/evaluate?as_of=${encodeURIComponent(asOf)}`, { method: 'POST' }),

  resolveAlert: (id) => request(`/api/v1/alerts/${id}/resolve`, { method: 'POST' }),

  health: () => request('/readyz'),
};
