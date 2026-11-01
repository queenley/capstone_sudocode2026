"""Browser-test fixture only: real platform routes with a scripted assistant and no provider access.

PYTHONPATH=tests:packages/backend-common:apps/ai-agent-service/src python -m uvicorn offline_api:app --port 18000
"""
import os
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

for name in ("OPENAI_API_KEY", "GOOGLE_API_KEY", "GEMINI_API_KEY", "GROQ_API_KEY", "NVIDIA_API_KEY",
             "TYPESAFE_API_KEY", "AI_GATEWAY_API_KEY", "LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY"):
    os.environ[name] = ""

from conftest import ScriptedAgent, create_test_app
from src.core.config import Settings
from src.db.session import Database
from scripts.seed.catalog import seed
from ai_agent_service.runtime import calls
from ai_agent_service.llm.factory import LLMFactory
from ai_agent_service.api.routes import welcome
from ai_agent_service.mcp.servers import memory
from ai_agent_service.components.clock import VIETNAM
from src.db.models import Customer


def no_model(*args, **kwargs):
    raise AssertionError("The offline browser fixture forbids model providers")


LLMFactory.create_llm = staticmethod(no_model)
assistant = ScriptedAgent()
for name in ("call_for_conversation", "stored_reply", "take_turn", "set_caller", "call_row"):
    setattr(calls, name, getattr(assistant, name))
temporary = tempfile.TemporaryDirectory(prefix="sudo-offline-browser-")
database = Database("sqlite:///" + str(Path(temporary.name) / "fixture.sqlite"))
database.migrate()
with database.sessions() as db:
    seed(db)
app = create_test_app(Settings(database_url="sqlite://", bank_bin="970436", bank_name="Fixture bank",
                               bank_account_no="0000000000", bank_account_name="OFFLINE TEST"), database)
app.include_router(welcome.router)


async def no_profile(customer_id, on=None):
    facts = []
    if customer_id.startswith("web:"):
        with database.sessions() as db:
            customer = db.get(Customer, customer_id[4:])
            # Synthetic ledger seed reserved for the welcome smoke test; other fixtures stay new.
            if customer and customer.full_name == "Khách Offline Welcome" and customer.deleted_at is None:
                today = datetime.now(VIETNAM).date()
                facts = [{"slot": "blocker", "value": "cần hỏi người nhà", "status": "active", "confidence": 1,
                          "valid_from": today.isoformat(), "valid_to": (today + timedelta(days=30)).isoformat(),
                          "source": {"call_id": "synthetic-prior-call", "turn": 1, "said_by": "customer"}}]
    return {"customer_id": customer_id, "facts": facts, "deleted_at": None, "deletion_pending": False}


async def no_identity(*args, **kwargs):
    return {"matches": []}


async def no_episodes(*args, **kwargs):
    return {"episodes": []}


memory.memory_get_profile = no_profile
memory.identity_find = no_identity
memory.memory_get_episodes = no_episodes
