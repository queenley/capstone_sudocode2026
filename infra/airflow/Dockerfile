# Airflow for the weekly improvement round (dags/improvement_weekly.py), with the agent in a venv of its own:
# the agent's pinned packages (langchain, pydantic, fastapi...) must not meet Airflow's constraints in one
# environment. The repository itself is mounted at /opt/telesales (docker-compose.airflow.yml), so the round runs the
# code and the scenario sets of the checkout.
FROM apache/airflow:2.10.5-python3.12

USER root
RUN python -m venv /opt/agent-venv && chown -R airflow: /opt/agent-venv
USER airflow
COPY packages/backend-common/requirements.txt /tmp/requirements-common.txt
COPY apps/ai-agent-service/requirements.txt /tmp/requirements-agent.txt
RUN /opt/agent-venv/bin/pip install --no-cache-dir -r /tmp/requirements-common.txt -r /tmp/requirements-agent.txt
