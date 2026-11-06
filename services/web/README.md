# services/web — web client (v0, A8)

A single static page: choose a demo preset, submit a complaint, poll the run, render the
determination (route, regulator, entity, basis, citations, escalation, verification).
**Appearance is not graded — kept deliberately minimal (≤2 days total across Slices 3 + 7).**

## Files
- `static/index.html`, `static/app.js`, `static/styles.css` — the client (vanilla JS, no build step).
- `fake_gateway.py` — a dev-only FastAPI fake of the gateway contract that also serves the static
  client same-origin, so the page works with zero other services. **Not** the real gateway (Jignas).

## Run against the fake gateway (standalone demo)
```bash
. .venv/bin/activate
uvicorn services.web.fake_gateway:app --port 8000
# open http://localhost:8000  (leave "Gateway base URL" blank = same origin)
```
Presets: #10 §4.1 bank FD → RBI (with the pinned reference passages), a §4.1 paraphrase, MF
redemption → SEBI, broker and bank charges → escalate (two regulators, F7), insurance → escalate
(out of corpus).

## Run against the real gateway (compose / Day-14 skeleton)
Serve the static files with the Compose stack. On port 8080, the client defaults
to `http://localhost:8000`; the Gateway base URL field can override it. The
gateway allows the web origin through CORS.
```bash
docker build -f services/web/Dockerfile -t orcas-web .
docker run --rm -p 8080:80 orcas-web
```

## Contract consumed
`POST /v1/complaints -> {run_id, status_url}`; `GET /v1/runs/{id} -> run_status.v1`
(`result` is a `determination.v1` when terminal); `GET /v1/runs/{id}/trace -> {events}` (the passages
each run retrieved); `POST /v1/runs/{id}/feedback {rating, reason}`. The fake gateway implements the
same four endpoints.

## Rendered
- Route/regulator/entity/timeline and basis; a **degraded banner** when a fallback path was used.
- **Citations** with the quote, a mark showing whether the cited chunk is among the passages *this
  run retrieved* (from its trace: ✓ / ✗), and the retrieved passage text in an expandable section.
  This is what demo #2 ("citations resolve to retrieved text") needs to show.
- **Escalation path**: reason code, reason and partial findings (document · clause · chunk).
- **Verification outcome** (passed, claims supported/checked, attempts), a **View run trace** link
  (demo #3), and **feedback buttons** (👍/👎 + optional reason).
- The client waits up to the "Wait for a result" time (default 180 s; a live model is slower than the
  stub). A run that ends without a determination shows that, with the trace link.
