(function () {
  const root = document.getElementById("admin-root");
  const esc = (v) => String(v == null ? "" : v).replace(/[&<>"']/g, c => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
  const n = (v) => Number.isFinite(Number(v)) ? Number(v) : 0;
  const FAILURE_LABELS = {
    retrieval_failure: "Retrieval failure",
    retrieval_ambiguity: "Retrieval ambiguity",
    query_drift: "Query drift",
    hallucination: "Hallucination",
    context_overflow: "Context overflow",
    entity_gap: "Entity gap",
    prompt_brittleness: "Prompt brittleness",
    ambiguous_prompt: "Ambiguous prompt",
    schema_violation: "Schema violation",
    tool_call_failure: "Tool call failure",
    tool_result_ignored: "Tool result ignored",
    citation_failure: "Citation failure",
    prompt_injection: "Prompt injection",
    sensitive_data_leak: "Sensitive data leak",
    instruction_violation: "Instruction violation",
    healthy: "Healthy",
  };

  function showError(message) {
    root.innerHTML = `<div class="error-banner">${esc(message)}</div>`;
  }

  function bar(label, value, max) {
    const count = n(value);
    const width = Math.max(0, Math.min(100, (count / Math.max(1, max)) * 100));
    return `
      <div class="admin-bar">
        <span class="admin-bar__label">${esc(label)}</span>
        <div class="admin-bar__track"><div class="admin-bar__fill" style="width:${width}%"></div></div>
        <span class="admin-bar__count">${count}</span>
      </div>`;
  }

  function date(value) {
    const ts = n(value);
    if (!ts) return "-";
    return new Date(ts * 1000).toLocaleDateString();
  }

  async function load() {
    try {
      const r = await fetch("/api/admin/stats");
      if (r.status === 401) {
        window.location.href = "/login";
        return;
      }
      if (r.status === 403) {
        showError("Staff access is required for this page.");
        return;
      }
      if (!r.ok) {
        showError("Could not load admin stats.");
        return;
      }
      const d = await r.json();
      const byF = (d.diagnoses && d.diagnoses.by_failure) || {};
      const maxF = Math.max(1, ...Object.values(byF).map(n));
      const bars = Object.keys(byF).length
        ? Object.entries(byF).sort((a, b) => n(b[1]) - n(a[1]))
          .map(([k, v]) => bar(FAILURE_LABELS[k] || k, v, maxF)).join("")
        : '<div class="empty">No diagnoses yet.</div>';
      const userRows = (d.recent_users || []).map(u =>
        `<tr><td>${esc(u.name)}</td><td>${esc(u.email)}</td><td>${date(u.created_at)}</td></tr>`
      ).join("") || '<tr><td colspan="3">No signups yet.</td></tr>';
      const leadRows = (((d.leads && d.leads.recent) || [])).map(l => `
        <tr>
          <td>${esc(l.email)}</td>
          <td>${esc(l.name || "-")}</td>
          <td>${esc(l.company || "-")}</td>
          <td>${esc(l.role || "-")}</td>
          <td>${esc(l.use_case || "-")}</td>
        </tr>`).join("") || '<tr><td colspan="5">No beta leads yet.</td></tr>';
      const funnel = d.funnel || {};
      const activation = d.activation || {};
      const diagnoses = d.diagnoses || {};
      const traces = d.traces || {};
      root.innerHTML = `
        <div class="admin-grid">
          <div class="admin-card"><div class="admin-card__val">${n(funnel.leads)}</div><div class="admin-card__label">Beta leads</div></div>
          <div class="admin-card"><div class="admin-card__val">${n(d.users)}</div><div class="admin-card__label">Total users</div></div>
          <div class="admin-card"><div class="admin-card__val">${n(activation.users_with_api_tokens)}</div><div class="admin-card__label">Token users</div></div>
          <div class="admin-card"><div class="admin-card__val">${n(activation.activated_product_users)}</div><div class="admin-card__label">Activated users</div></div>
          <div class="admin-card"><div class="admin-card__val">${n(diagnoses.total)}</div><div class="admin-card__label">Diagnoses</div></div>
          <div class="admin-card"><div class="admin-card__val">${n(diagnoses.failing)}</div><div class="admin-card__label">Failing</div></div>
          <div class="admin-card"><div class="admin-card__val">${n(traces.traces)}</div><div class="admin-card__label">Traces</div></div>
          <div class="admin-card"><div class="admin-card__val">$${n(traces.cost_usd).toFixed(4)}</div><div class="admin-card__label">Est. cost</div></div>
        </div>
        <div class="admin-section"><h2>Traction funnel</h2>
          ${bar("Beta leads", funnel.leads, Math.max(1, n(funnel.leads)))}
          ${bar("Accounts", funnel.accounts, Math.max(1, n(funnel.leads)))}
          ${bar("API token users", funnel.users_with_api_tokens, Math.max(1, n(funnel.leads)))}
          ${bar("Activated users", funnel.activated_product_users, Math.max(1, n(funnel.leads)))}
        </div>
        <div class="admin-section"><h2>Failure breakdown</h2>${bars}</div>
        <div class="admin-section"><h2>Recent beta leads</h2>
          <table class="admin-table"><thead><tr><th>Email</th><th>Name</th><th>Company</th><th>Role</th><th>Use case</th></tr></thead><tbody>${leadRows}</tbody></table>
        </div>
        <div class="admin-section"><h2>Recent signups</h2>
          <table class="admin-table"><thead><tr><th>Name</th><th>Email</th><th>Joined</th></tr></thead><tbody>${userRows}</tbody></table>
        </div>`;
    } catch (_) {
      showError("Admin stats failed to render.");
    }
  }

  load();
})();
