from fastapi import HTTPException
from src.security.auth import resolve_staff


def bearer(request):
    header = request.headers.get("Authorization", "")
    if not header.startswith("Bearer "):
        raise HTTPException(401, "Bearer authentication is required")
    return header[7:]


def staff(request, roles):
    with request.app.state.database.sessions() as db:
        role, actor = resolve_staff(
            db, request.app.state.security, bearer(request), roles
        )
        request.state.actor_id = actor
        return role


def resources(request):
    return request.app.state.database.sessions(), request.app.state.security
