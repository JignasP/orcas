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
Presets: #10 §4.1 bank FD → RBI (with the real pinned citations), MF redemption → SEBI,
insurance → escalate (out of corpus).

## Run against the real gateway (compose / Day-14 skeleton)
Serve the static files (nginx image below) and set the **Gateway base URL** field to the
published gateway, e.g. `http://localhost:8000`. (Cross-origin calls need CORS on the gateway.)
```bash
docker build -f services/web/Dockerfile -t orcas-web .
docker run --rm -p 8080:80 orcas-web
```

## Contract consumed
`POST /v1/complaints -> {run_id, status_url}`; `GET /v1/runs/{id} -> run_status.v1`
(`result` is a `determination.v1` when terminal). Built from the documented contract until
Jignas commits the gateway schemas.

## Deferred to Slice 7
Expandable full passage text, escalation-path detail, and feedback buttons
(`POST /v1/runs/{id}/feedback`).
