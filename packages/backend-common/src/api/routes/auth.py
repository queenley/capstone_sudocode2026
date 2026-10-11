from fastapi import APIRouter, Request
from src.security.auth import login
from src.api.schemas import LoginInput

router = APIRouter(prefix="/api")


@router.post("/auth/login")
def staff_login(data: LoginInput, request: Request):
    with request.app.state.database.sessions() as db:
        return login(db, request.app.state.security, data.username, data.password)
