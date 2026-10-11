from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.responses import JSONResponse

from src.api.routes.auth import router as auth_router
from src.api.routes.customer import router as customer_router
from src.api.routes.conversations import identify, verify
from src.api.routes.admin import add_user, users, disable_user
from src.core.service_runtime import configure_service, database_ready


@asynccontextmanager
async def lifespan(app: FastAPI):
    database = configure_service(app)
    yield
    database.engine.dispose()


app = FastAPI(title="Identity Service", version="0.1.0", lifespan=lifespan)
app.include_router(auth_router)
app.include_router(customer_router)
app.add_api_route(
    "/api/conversations/{conversation_id}/identity/challenge",
    identify,
    methods=["POST"],
)
app.add_api_route(
    "/api/conversations/{conversation_id}/identity/verify",
    verify,
    methods=["POST"],
)
app.add_api_route("/api/admin/users", add_user, methods=["POST"], status_code=201)
app.add_api_route("/api/admin/users", users, methods=["GET"])
app.add_api_route("/api/admin/users/{user_id}", disable_user, methods=["DELETE"])


@app.get("/health")
def health():
    return {"status": "ok", "service": "identity"}


@app.get("/health/ready")
def ready():
    if database_ready(app):
        return {"status": "ready"}
    return JSONResponse(status_code=503, content={"status": "not ready"})
