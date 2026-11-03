# ORCAS — convenience targets (Tahir's eval/retrieval). Jignas owns the full stack targets
# (compose up, loadtest); this Makefile currently covers what Tahir's slices provide.
.PHONY: install-dev ingest eval test demo up down doctor loadtest

up:
	docker compose up --build -d

down:
	docker compose down

doctor:
	python scripts/doctor.py

loadtest:
	locust -f loadtest/locustfile.py --headless --host http://localhost:8000 --users 10 --spawn-rate 2 --run-time 15m --stop-timeout 180

ingest:
	python -m services.ingest

eval:
	python -m eval.run_eval

# Everything the test suite needs (all services + eval + test tools)
install-dev:
	python -m pip install -r requirements-dev.txt

# Tests that need the built index skip until `make ingest` has run
test:
	python -m pytest tests -q

demo:
	python scripts/demo/initial_demo.py
