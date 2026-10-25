.PHONY: dev up down seed test eval

dev up:
	docker compose up --build

down:
	docker compose down

seed:
	docker compose run --rm seed

test:
	python -m pytest -q
	cd apps/web && npm run typecheck

eval:
	python evaluation/harness/evaluate.py
