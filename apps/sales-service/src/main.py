from contextlib import asynccontextmanager
from fastapi import APIRouter, FastAPI
from fastapi.responses import JSONResponse

from src.api.routes import conversations as conversation_routes
from src.api.routes.admin import proposals, review
from src.api.routes.staff import router as staff_router
from src.core.service_runtime import configure_service, database_ready


@asynccontextmanager
async def lifespan(app: FastAPI):
    database = configure_service(app)
    yield
    database.engine.dispose()


app = FastAPI(title="Sales Service", version="0.1.0", lifespan=lifespan)
sales_routes = APIRouter(prefix="/api")
sales_routes.add_api_route(
    "/conversations", conversation_routes.new_conversation,
    methods=["POST"], status_code=201,
)
sales_routes.add_api_route(
    "/conversations/{conversation_id}", conversation_routes.get_conversation,
    methods=["GET"],
)
sales_routes.add_api_route(
    "/conversations/{conversation_id}/messages", conversation_routes.buyer_human_message,
    methods=["POST"],
)
sales_routes.add_api_route(
    "/conversations/{conversation_id}/end", conversation_routes.end,
    methods=["POST"],
)
sales_routes.add_api_route(
    "/conversations/{conversation_id}/brief", conversation_routes.brief,
    methods=["GET"],
)
sales_routes.add_api_route(
    "/conversations/{conversation_id}/orders", conversation_routes.create_order,
    methods=["POST"], status_code=201,
)
sales_routes.add_api_route(
    "/conversations/{conversation_id}/feedback", conversation_routes.feedback,
    methods=["POST"], status_code=201,
)
app.include_router(sales_routes)
app.include_router(staff_router)
app.add_api_route("/api/admin/proposals", proposals, methods=["GET"])
app.add_api_route(
    "/api/admin/proposals/{proposal_id}/review",
    review,
    methods=["POST"],
)


@app.get("/health")
def health():
    return {"status": "ok", "service": "sales"}


@app.get("/health/ready")
def ready():
    if database_ready(app):
        return {"status": "ready"}
    return JSONResponse(status_code=503, content={"status": "not ready"})
