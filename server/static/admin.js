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

  function boolLabel(value) {
    if (value === true) return "yes";
    if (value === false) return "no";
    return "-";
  }

  function formBool(value) {
    if (value === "yes") return true;
    if (value === "no") return false;
    return null;
  }

  function bindTractionForm() {
    const form = document.getElementById("traction-form");
    if (!form) return;
    const msg = document.getElementById("traction-form-msg");
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      const submit = form.querySelector("button[type='submit']");
      const field = (name) => (form.elements[name] && form.elements[name].value || "").trim();
      const payload = {
        lead_email: field("lead_email"),
        contact_name: field("contact_name"),
        company: field("company"),
        source: field("source") || "manual",
        failure_summary: field("failure_summary"),
        failure_type: field("failure_type"),
        diagnosis_accepted: formBool(field("diagnosis_accepted")),
        fix_worked: formBool(field("fix_worked")),
        would_pay: formBool(field("would_pay")),
        repeat_usage: formBool(field("repeat_usage")),
        status: field("status") || "new",
        notes: field("notes"),
      };
      if (!payload.failure_summary) {
        if (msg) msg.textContent = "Add the real failure first.";
        return;
      }
      if (submit) submit.disabled = true;
      if (msg) msg.textContent = "Saving...";
      try {
        const r = await fetch("/api/admin/traction/interviews", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        });
        if (!r.ok) throw new Error("save failed");
        form.reset();
        if (msg) msg.textContent = "Saved.";
        await load();
      } catch (_) {
        if (msg) msg.textContent = "Could not save.";
      } finally {
        if (submit) submit.disabled = false;
      }
    });
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
      const traction = d.traction || {};
      const tractionRows = ((traction.recent || [])).map(i => `
        <tr>
          <td>${esc(date(i.updated_at))}</td>
          <td>${esc(i.lead_email || i.contact_name || "-")}</td>
          <td>${esc(i.company || "-")}</td>
          <td>${esc(i.failure_type || "-")}</td>
          <td>${esc(i.failure_summary || "-")}</td>
          <td>${esc(boolLabel(i.diagnosis_accepted))}</td>
          <td>${esc(boolLabel(i.fix_worked))}</td>
          <td>${esc(boolLabel(i.would_pay))}</td>
          <td>${esc(boolLabel(i.repeat_usage))}</td>
        </tr>`).join("") || '<tr><td colspan="9">No real failure interviews yet.</td></tr>';
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
          <div class="admin-card"><div class="admin-card__val">${n(traction.failures_submitted)}</div><div class="admin-card__label">Real failures</div></div>
          <div class="admin-card"><div class="admin-card__val">${n(traction.diagnosis_accepted)}</div><div class="admin-card__label">Accepted</div></div>
          <div class="admin-card"><div class="admin-card__val">${n(traction.fix_worked)}</div><div class="admin-card__label">Fix worked</div></div>
          <div class="admin-card"><div class="admin-card__val">${n(traction.would_pay)}</div><div class="admin-card__label">Would pay</div></div>
        </div>
        <div class="admin-section"><h2>Traction funnel</h2>
          ${bar("Beta leads", funnel.leads, Math.max(1, n(funnel.leads)))}
          ${bar("Accounts", funnel.accounts, Math.max(1, n(funnel.leads)))}
          ${bar("API token users", funnel.users_with_api_tokens, Math.max(1, n(funnel.leads)))}
          ${bar("Activated users", funnel.activated_product_users, Math.max(1, n(funnel.leads)))}
          ${bar("Real failures submitted", traction.failures_submitted, Math.max(1, n(funnel.leads)))}
          ${bar("Diagnosis accepted", traction.diagnosis_accepted, Math.max(1, n(traction.failures_submitted)))}
          ${bar("Fix worked", traction.fix_worked, Math.max(1, n(traction.failures_submitted)))}
          ${bar("Would pay", traction.would_pay, Math.max(1, n(traction.failures_submitted)))}
        </div>
        <div class="admin-section"><h2>Log real failure interview</h2>
          <form class="admin-form" id="traction-form">
            <div class="admin-form__grid">
              <label>Email<input name="lead_email" type="email" placeholder="founder@company.com"></label>
              <label>Name<input name="contact_name" placeholder="Founder name"></label>
              <label>Company<input name="company" placeholder="Company"></label>
            </div>
            <div class="admin-form__grid">
              <label>Source
                <select name="source">
                  <option>manual</option>
                  <option>dev.to</option>
                  <option>discord</option>
                  <option>linkedin</option>
                  <option>twitter</option>
                  <option>github</option>
                  <option>landing</option>
                </select>
              </label>
              <label>Failure type
                <select name="failure_type">
                  <option value="">unknown</option>
                  <option>retrieval_failure</option>
                  <option>hallucination</option>
                  <option>prompt_brittleness</option>
                  <option>prompt_injection</option>
                  <option>schema_violation</option>
                  <option>tool_call_failure</option>
                  <option>citation_failure</option>
                  <option>instruction_violation</option>
                  <option>sensitive_data_leak</option>
                </select>
              </label>
              <label>Status
                <select name="status">
                  <option>new</option>
                  <option>diagnosed</option>
                  <option>fixed</option>
                  <option>follow_up</option>
                  <option>closed</option>
                </select>
              </label>
            </div>
            <label>Real failure<textarea name="failure_summary" placeholder="What was the bad output? How did they know it was wrong?" required></textarea></label>
            <div class="admin-form__grid">
              <label>Diagnosis accepted
                <select name="diagnosis_accepted"><option value="">unknown</option><option value="yes">yes</option><option value="no">no</option></select>
              </label>
              <label>Fix worked
                <select name="fix_worked"><option value="">unknown</option><option value="yes">yes</option><option value="no">no</option></select>
              </label>
              <label>Would pay
                <select name="would_pay"><option value="">unknown</option><option value="yes">yes</option><option value="no">no</option></select>
              </label>
            </div>
            <div class="admin-form__grid">
              <label>Repeat usage
                <select name="repeat_usage"><option value="">unknown</option><option value="yes">yes</option><option value="no">no</option></select>
              </label>
              <label>Notes<input name="notes" placeholder="Price sensitivity, next step, objection"></label>
            </div>
            <div class="admin-form__actions">
              <button class="btn btn--primary btn--sm" type="submit">Save interview</button>
              <span class="admin-form__msg" id="traction-form-msg"></span>
            </div>
          </form>
          <table class="admin-table"><thead><tr><th>Updated</th><th>Contact</th><th>Company</th><th>Failure</th><th>Summary</th><th>Accepted</th><th>Fix</th><th>Pay</th><th>Repeat</th></tr></thead><tbody>${tractionRows}</tbody></table>
        </div>
        <div class="admin-section"><h2>Failure breakdown</h2>${bars}</div>
        <div class="admin-section"><h2>Recent beta leads</h2>
          <table class="admin-table"><thead><tr><th>Email</th><th>Name</th><th>Company</th><th>Role</th><th>Use case</th></tr></thead><tbody>${leadRows}</tbody></table>
        </div>
        <div class="admin-section"><h2>Recent signups</h2>
          <table class="admin-table"><thead><tr><th>Name</th><th>Email</th><th>Joined</th></tr></thead><tbody>${userRows}</tbody></table>
        </div>`;
      bindTractionForm();
    } catch (_) {
      showError("Admin stats failed to render.");
    }
  }

  load();
})();
