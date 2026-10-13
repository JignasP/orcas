// ORCAS web client v0 — submit a complaint, poll the run, render the determination.
// Talks to the gateway contract: POST /v1/complaints -> {run_id, status_url};
// GET /v1/runs/{id} -> run_status.v1 (with result: determination.v1 when terminal).

"use strict";

const $ = (id) => document.getElementById(id);
const TERMINAL = ["completed", "escalated", "failed"];

let _base = "";      // gateway base used for the current run (for the feedback call)
let _runId = null;

const PRESETS = {
  bank_fd: "I invested in a fixed deposit through my bank's app. The interest credited is lower than what I was promised. I want to complain to SEBI.",
  mf: "My mutual fund redemption has been delayed by two weeks and the NAV on my statement looks wrong. The AMC has not responded.",
  out_of_corpus: "My life insurance policy claim was rejected unfairly by the insurer. I want this routed for redressal.",
};

// Gateway base: remembered in localStorage, else same origin (works when the fake
// gateway serves this page). Override live via the input for a cross-origin gateway.
function gatewayBase() {
  const v = $("gateway").value.trim();
  return v.replace(/\/$/, "");
}

function todayISO(offsetDays = 0) {
  const d = new Date();
  d.setDate(d.getDate() + offsetDays);
  return d.toISOString().slice(0, 10);
}

function init() {
  $("gateway").value = localStorage.getItem("orcas_gateway") || "";
  $("date_of_event").value = todayISO(-14);
  $("date_filed").value = todayISO(0);
  $("preset").addEventListener("change", (e) => {
    if (PRESETS[e.target.value]) $("text").value = PRESETS[e.target.value];
  });
  $("complaint-form").addEventListener("submit", onSubmit);
}

function buildComplaint() {
  return {
    client_id: $("client_id").value.trim(),
    is_synthetic: $("is_synthetic").checked,
    channel: $("channel").value,
    text: $("text").value.trim(),
    date_of_event: $("date_of_event").value,
    date_filed: $("date_filed").value,
  };
}

async function onSubmit(e) {
  e.preventDefault();
  const base = gatewayBase();
  _base = base;
  localStorage.setItem("orcas_gateway", base);
  const btn = $("submit");
  btn.disabled = true;
  $("status-card").hidden = false;
  $("result").innerHTML = "";
  $("run-id").textContent = "…";
  setStatus("submitting");
  try {
    const res = await fetch(`${base}/v1/complaints`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(buildComplaint()),
    });
    if (!res.ok) {
      const body = await res.text();
      throw new Error(`submit failed (${res.status}): ${body}`);
    }
    const { run_id } = await res.json();
    _runId = run_id;
    $("run-id").textContent = run_id;
    await poll(base, run_id);
  } catch (err) {
    setStatus("failed");
    $("result").innerHTML = `<p class="err">${escapeHtml(err.message)}</p>`;
  } finally {
    btn.disabled = false;
  }
}

async function poll(base, runId) {
  for (let i = 0; i < 60; i++) {
    const res = await fetch(`${base}/v1/runs/${runId}`);
    if (!res.ok) throw new Error(`poll failed (${res.status})`);
    const run = await res.json();
    setStatus(run.status);
    if (TERMINAL.includes(run.status)) return render(run);
    await sleep(1000);
  }
  throw new Error("timed out waiting for a terminal status");
}

function setStatus(s) {
  const el = $("status");
  el.textContent = s;
  el.className = "badge " + s;
}

function render(run) {
  const d = run.result;
  if (!d) {
    $("result").innerHTML = `<p>No determination returned.</p>`;
    return;
  }
  const parts = [];
  parts.push(`<dl class="kv">
    <dt>Route</dt><dd><strong>${esc(d.route)}</strong></dd>
    <dt>Regulator</dt><dd>${esc(d.regulator)}</dd>
    <dt>Entity type</dt><dd>${esc(d.entity_type)}</dd>
    ${d.timeline && d.timeline.days != null
      ? `<dt>Timeline</dt><dd>${esc(d.timeline.days)} days</dd>` : ""}
    <dt>Index version</dt><dd><code>${esc(d.index_version || "")}</code></dd>
    <dt>Degraded</dt><dd>${d.degraded ? "yes ⚠️" : "no"}</dd>
  </dl>`);
  if (d.basis) parts.push(`<p><strong>Basis.</strong> ${esc(d.basis)}</p>`);

  // Escalation path + reason
  if (d.escalation) {
    const e = d.escalation;
    const findings = (e.partial_findings && e.partial_findings.length)
      ? `<div class="meta">Partial findings: ${esc(e.partial_findings.join("; "))}</div>` : "";
    parts.push(`<div class="escalation">
      <strong>Escalated to a human.</strong>
      <div class="meta">reason: <code>${esc(e.reason_code)}</code></div>
      <div>${esc(e.reason || "")}</div>${findings}</div>`);
  }

  // Citations with expandable full passage text
  const cites = d.citations || [];
  if (cites.length) {
    parts.push(`<h3>Citations (${cites.length})</h3>`);
    for (const c of cites) {
      const passage = c.passage_text || c.quote_span || "";
      parts.push(`<details class="citation">
        <summary>${esc(c.doc_title || c.doc_id)} · clause ${esc(c.clause || "")}
          <span class="meta">(${esc(c.circular_ref || "")} · chunk ${esc((c.chunk_id || "").slice(0, 12))}…)</span></summary>
        <div class="quote">"${esc(c.quote_span || "")}"</div>
        ${c.passage_text ? `<div class="passage">${esc(passage)}</div>` : ""}
      </details>`);
    }
  }

  // Verification outcome
  if (d.verification) {
    const v = d.verification;
    parts.push(`<div class="verify ${v.passed ? "ok" : "bad"}">
      Verification: <strong>${v.passed ? "passed ✓" : "failed ✗"}</strong>
      — ${v.claims_supported ?? "?"}/${v.claims_checked ?? "?"} claims supported,
      ${v.attempts ?? 1} attempt(s)</div>`);
  }

  // Feedback buttons
  parts.push(`<div class="feedback">
    <span>Was this routing helpful?</span>
    <button type="button" class="fb" data-rating="up">👍 Up</button>
    <button type="button" class="fb" data-rating="down">👎 Down</button>
    <input id="fb-reason" type="text" placeholder="optional reason" />
    <span id="fb-ack" class="meta"></span>
  </div>`);

  $("result").innerHTML = parts.join("\n");
  for (const b of document.querySelectorAll(".fb")) {
    b.addEventListener("click", () => sendFeedback(b.dataset.rating));
  }
}

async function sendFeedback(rating) {
  if (!_runId) return;
  const reason = ($("fb-reason").value || "").trim();
  const ack = $("fb-ack");
  try {
    const res = await fetch(`${_base}/v1/runs/${_runId}/feedback`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ rating, reason }),
    });
    ack.textContent = res.ok ? `thanks — recorded "${rating}"` : `feedback failed (${res.status})`;
  } catch (err) {
    ack.textContent = "feedback failed: " + err.message;
  }
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const esc = escapeHtml;
function escapeHtml(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

init();
