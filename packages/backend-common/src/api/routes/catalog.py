from decimal import Decimal
from fastapi import APIRouter, Request, Query
from src.commerce.service import CatalogService

router = APIRouter(prefix="/api")


@router.get("/catalog")
def catalog(
    request: Request,
    q: str = Query(default="", max_length=200),
    budget: Decimal | None = Query(default=None, ge=0),
    category: str | None = Query(default=None, max_length=100),
    limit: int = Query(default=50, ge=1, le=500),
):
    with request.app.state.database.sessions() as db:
        return CatalogService(db).search(q, budget, category, limit)


@router.get("/catalog/payment-methods")
def payment_methods(request: Request):
    settings = request.app.state.security.settings
    bank = bool(settings.bank_bin and settings.bank_account_no)
    return {
        "cod": {"enabled": True, "max_total": "10000000"},
        "bank_transfer": {"enabled": bank, "bank_name": settings.bank_name if bank else None},
    }


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
