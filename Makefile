.PHONY: demo eval check test
demo:   ## trace one packet through every step
	python -m staged_pipeline demo
eval:   ## run all variants and write results/
	python -m staged_pipeline eval
check:  ## eval + release gate against evals/baseline.json
	python -m staged_pipeline eval --check
test:
	python -m pytest -q
