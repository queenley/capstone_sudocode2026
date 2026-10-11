from contextlib import asynccontextmanager
from decimal import Decimal

from fastapi import FastAPI, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text

from src.api.routes.admin import add_product, stock, add_promotion
from src.api.routes.seller import router as seller_router
from src.commerce.service import CatalogService
from src.core.service_runtime import configure_service


@asynccontextmanager
async def lifespan(app: FastAPI):
    database = configure_service(app)
    yield
    database.engine.dispose()


app = FastAPI(title="Commerce Service", version="0.1.0", lifespan=lifespan)
app.include_router(seller_router)
app.add_api_route("/api/admin/catalog", add_product, methods=["POST"], status_code=201)
app.add_api_route("/api/admin/inventory/{sku_code}", stock, methods=["PUT"])
app.add_api_route("/api/admin/promotions", add_promotion, methods=["POST"], status_code=201)


@app.get("/health")
def health():
    return {"status": "ok", "service": "commerce"}


@app.get("/health/ready")
def ready(request: Request):
    try:
        with request.app.state.database.engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return {"status": "ready"}
    except Exception:
        return JSONResponse(status_code=503, content={"status": "not ready"})


@app.get("/api/catalog")
def catalog(
    request: Request,
    q: str = Query(default="", max_length=200),
    budget: Decimal | None = Query(default=None, ge=0),
):
    with request.app.state.database.sessions() as db:
        return CatalogService(db).search(q, budget)


@app.get("/api/catalog/{sku_code}")
def product(sku_code: str, request: Request):
    with request.app.state.database.sessions() as db:
        return CatalogService(db).get(sku_code)


@app.get("/api/catalog/{sku_code}/quote")
def quote(
    sku_code: str,
    request: Request,
    quantity: int = Query(default=1, ge=1, le=100),
    channel: str = Query(default="web", max_length=50),
):
    with request.app.state.database.sessions() as db:
        return CatalogService(db).quote(sku_code, quantity, channel)
