from decimal import Decimal
from fastapi import APIRouter, Request, Query
from src.commerce.service import CatalogService

router = APIRouter(prefix="/api")


@router.get("/catalog")
def catalog(
    request: Request,
    q: str = Query(default="", max_length=200),
    budget: Decimal | None = Query(default=None, ge=0),
):
    with request.app.state.database.sessions() as db:
        return CatalogService(db).search(q, budget)


@router.get("/catalog/{sku_code}")
def product(sku_code: str, request: Request):
    with request.app.state.database.sessions() as db:
        return CatalogService(db).get(sku_code)


@router.get("/catalog/{sku_code}/quote")
def quote(
    sku_code: str,
    request: Request,
    quantity: int = Query(default=1, ge=1, le=100),
    channel: str = Query(default="web", max_length=50),
):
    with request.app.state.database.sessions() as db:
        return CatalogService(db).quote(sku_code, quantity, channel)
