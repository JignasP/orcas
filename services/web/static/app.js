// ORCAS web client v0 — submit a complaint, poll the run, render the determination.
// Talks to the gateway contract: POST /v1/complaints -> {run_id, status_url};
// GET /v1/runs/{id} -> run_status.v1 (with result: determination.v1 when terminal).

"use strict";

const $ = (id) => document.getElementById(id);
const TERMINAL = ["completed", "escalated", "failed"];

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
    <dt>Index version</dt><dd><code>${esc(d.index_version || "")}</code></dd>
    <dt>Degraded</dt><dd>${d.degraded ? "yes" : "no"}</dd>
  </dl>`);
  if (d.basis) parts.push(`<p><strong>Basis.</strong> ${esc(d.basis)}</p>`);

  if (d.escalation) {
    parts.push(`<div class="escalation"><strong>Escalated:</strong>
      ${esc(d.escalation.reason_code)} — ${esc(d.escalation.reason || "")}</div>`);
  }

  const cites = d.citations || [];
  if (cites.length) {
    parts.push(`<h3>Citations (${cites.length})</h3>`);
    for (const c of cites) {
      parts.push(`<div class="citation">
        <div class="meta">${esc(c.doc_title || c.doc_id)} · ${esc(c.circular_ref || "")} · clause ${esc(c.clause || "")}
          · chunk <code>${esc((c.chunk_id || "").slice(0, 12))}…</code></div>
        <div class="quote">"${esc(c.quote_span || "")}"</div>
      </div>`);
    }
  }

  if (d.verification) {
    const v = d.verification;
    parts.push(`<p class="meta">Verification: ${v.passed ? "passed" : "failed"}
      (${v.claims_supported ?? "?"}/${v.claims_checked ?? "?"} claims, ${v.attempts ?? 1} attempt(s))</p>`);
  }
  $("result").innerHTML = parts.join("\n");
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const esc = escapeHtml;
function escapeHtml(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

init();
