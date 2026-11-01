from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text

from src.api.routes.admin import add_product, stock, add_promotion
from src.api.routes.seller import router as seller_router
from src.api.routes.catalog import router as catalog_router
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


app.include_router(catalog_router)
