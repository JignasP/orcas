# ORCAS — convenience targets (Tahir's eval/retrieval). Jignas owns the full stack targets
# (compose up, loadtest); this Makefile currently covers what Tahir's slices provide.
.PHONY: ingest eval test

ingest:
	python -m services.ingest

eval:
	python -m eval.run_eval

test:
	python -m pytest tests -q
