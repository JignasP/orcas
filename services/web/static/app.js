// ORCAS web client — submit a complaint, poll the run, render the determination.
// Talks to the gateway contract: POST /v1/complaints -> {run_id, status_url};
// GET /v1/runs/{id} -> run_status.v1 (with result: determination.v1 when terminal);
// GET /v1/runs/{id}/trace -> ordered run events (used to show what the run retrieved).

"use strict";

const $ = (id) => document.getElementById(id);
const TERMINAL = ["completed", "escalated", "failed"];
const DEFAULT_TIMEOUT_S = 180;  // a live model is much slower than the stub

let _base = "";      // gateway base used for the current run (for the feedback call)
let _runId = null;

const PRESETS = {
  bank_fd: "I invested in a fixed deposit through my bank's app. The interest credited is lower than what I was promised. I want to complain to SEBI.",
  bank_fd_paraphrase: "Opened an FD via net banking; maturity interest credited is less than the promised rate. Filing a grievance with SEBI.",
  mf: "My mutual fund redemption has been delayed by two weeks and the NAV on my statement looks wrong. The AMC has not responded.",
  split: "My broker debited my linked bank account for charges I never agreed to, and the bank also added its own fee.",
  out_of_corpus: "My life insurance policy claim was rejected unfairly by the insurer. I want this routed for redressal.",
};

// Gateway base: the Compose web service uses port 8080 and the API uses port 8000.
// The standalone fake gateway serves both from port 8000.
function gatewayBase() {
  const v = $("gateway").value.trim();
  return v.replace(/\/$/, "");
}

function pollTimeoutSeconds() {
  const v = parseInt($("poll_timeout").value, 10);
  return Number.isFinite(v) && v > 0 ? v : DEFAULT_TIMEOUT_S;
}

function stored(key) {
  try { return localStorage.getItem(key); } catch (e) { return null; }
}

function store(key, value) {
  try { localStorage.setItem(key, value); } catch (e) { /* private mode: not remembered */ }
}

function todayISO(offsetDays = 0) {
  const d = new Date();
  d.setDate(d.getDate() + offsetDays);
  return d.toISOString().slice(0, 10);
}

function init() {
  $("gateway").value = stored("orcas_gateway") ||
    (window.location.port === "8080" ? `${window.location.protocol}//${window.location.hostname}:8000` : "");
  $("poll_timeout").value = stored("orcas_poll_timeout") || DEFAULT_TIMEOUT_S;
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
  store("orcas_gateway", base);
  store("orcas_poll_timeout", String(pollTimeoutSeconds()));
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
  const deadline = Date.now() + pollTimeoutSeconds() * 1000;
  while (Date.now() < deadline) {
    const res = await fetch(`${base}/v1/runs/${runId}`);
    if (!res.ok) throw new Error(`poll failed (${res.status})`);
    const run = await res.json();
    setStatus(run.status);
    if (TERMINAL.includes(run.status)) return render(base, run, await fetchRetrieved(base, runId));
    await sleep(1000);
  }
  throw new Error(`no terminal status after ${pollTimeoutSeconds()} s; the run may still finish — ` +
                  `check ${traceUrl(base, runId)}`);
}

// chunk_id -> passage text, for every passage the run retrieved; null if the trace is unavailable.
async function fetchRetrieved(base, runId) {
  try {
    const res = await fetch(traceUrl(base, runId));
    if (!res.ok) return null;
    const retrieved = new Map();
    for (const ev of (await res.json()).events || []) {
      if (ev.kind !== "tool_call") continue;
      for (const p of (ev.payload && ev.payload.passages) || []) {
        if (p.chunk_id && !retrieved.has(p.chunk_id)) retrieved.set(p.chunk_id, p.text || "");
      }
    }
    return retrieved;
  } catch (err) {
    return null;
  }
}

function traceUrl(base, runId) {
  return `${base}/v1/runs/${runId}/trace`;
}

function setStatus(s) {
  const el = $("status");
  el.textContent = s;
  el.className = "badge " + s;
}

function finding(f) {
  if (typeof f === "string") return f;
  const doc = f.doc_title || f.doc_id || "unknown document";
  const clause = f.clause || f.clause_id;
  const chunk = f.chunk_id ? ` · chunk ${f.chunk_id.slice(0, 12)}…` : "";
  return `${doc}${clause ? ` · clause ${clause}` : ""}${chunk}`;
}

function render(base, run, retrieved) {
  const d = run.result;
  const trace = `<p class="meta"><a href="${esc(traceUrl(base, run.run_id))}" target="_blank" rel="noopener">View run trace (JSON)</a></p>`;
  if (!d) {
    $("result").innerHTML = `<p class="err">The run ${run.status === "failed" ? "failed" : "ended"} ` +
      `before producing a determination.</p>${trace}`;
    return;
  }
  const parts = [];
  if (d.degraded) {
    parts.push(`<div class="banner warn"><strong>Degraded run.</strong> A fallback path was used, ` +
               `so treat this result as unverified until a grievance officer reviews it.</div>`);
  }
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
    const items = (e.partial_findings || []).map((f) => `<li>${esc(finding(f))}</li>`).join("");
    const findings = items ? `<div class="meta">Partial findings for the officer:</div><ul class="findings">${items}</ul>` : "";
    parts.push(`<div class="escalation">
      <strong>Escalated to a human.</strong>
      <div class="meta">reason: <code>${esc(e.reason_code)}</code></div>
      <div>${esc(e.reason || "")}</div>${findings}</div>`);
  }

  // Citations: the quote, whether this run retrieved the chunk, and the retrieved text
  const cites = d.citations || [];
  if (cites.length) {
    parts.push(`<h3>Citations (${cites.length})</h3>`);
    for (const c of cites) {
      const text = retrieved ? retrieved.get(c.chunk_id) : undefined;
      const mark = !retrieved ? ""
        : text !== undefined ? `<span class="retrieved ok">retrieved in this run ✓</span>`
        : `<span class="retrieved bad">not among this run's retrieved passages ✗</span>`;
      parts.push(`<details class="citation">
        <summary>${esc(c.doc_title || c.doc_id)} · clause ${esc(c.clause || "")} ${mark}
          <span class="meta">(${esc(c.circular_ref || "")} · chunk ${esc((c.chunk_id || "").slice(0, 12))}…)</span></summary>
        <div class="quote">"${esc(c.quote_span || "")}"</div>
        ${text ? `<div class="passage">${esc(text)}</div>` : ""}
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
  parts.push(trace);

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
