# The weekly improvement round (Gap Loop + Reflection) as a one-shot container: AWS runs it as a Fargate task on an
# EventBridge schedule (docs/deployment/aws-plan.md, 3.7), in place of Airflow.
#
#   docker build -f infra/improve/Dockerfile -t telesales-improve .
#   docker run --rm --env-file .env telesales-improve learn     # Monday: restate gaps, R0, learn, proposals
#   docker run --rm --env-file .env telesales-improve tick      # every few hours: expire, or measure once decided
#
# The round needs the repository's layout, not the service image's: run_eval.py at the root, the scenario sets
# (data/reflection, data/gap-loop), config/prompts and docs/evaluation (the extractor's contract hashes). Only those
# are copied (Dockerfile.dockerignore beside this file is a whitelist).
# Mount on EFS, as the agent does: apps/ai-agent-service/data/{skills,improvement,kb}, and EVAL_RUNS_DIR (a round's
# lessons and review files stay between the learn and the measure tasks).
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONUTF8=1 \
    PYTHONPATH=/opt/telesales/apps/ai-agent-service/src:/opt/telesales/packages/backend-common \
    IMPROVE_REPO=/opt/telesales \
    EVAL_RUNS_DIR=/opt/telesales/evaluation/runs
WORKDIR /opt/telesales
RUN apt-get update && apt-get install -y --no-install-recommends libsndfile1 && rm -rf /var/lib/apt/lists/*

COPY packages/backend-common/requirements.txt /tmp/requirements-common.txt
COPY apps/ai-agent-service/requirements.txt /tmp/requirements-agent.txt
RUN pip install --no-cache-dir -r /tmp/requirements-common.txt -r /tmp/requirements-agent.txt

COPY . /opt/telesales
# uid 1000, as the agent image's "app": files written on the shared EFS stay writable by both.
RUN useradd --uid 1000 --create-home app \
    && mkdir -p evaluation/runs apps/ai-agent-service/data/skills apps/ai-agent-service/data/improvement \
    && chown -R app:app /opt/telesales
USER app
ENTRYPOINT ["python", "/opt/telesales/infra/improve/run.py"]
CMD ["tick"]
