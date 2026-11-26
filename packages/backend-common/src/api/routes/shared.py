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


def client_ip(request):
    """The customer's address as the gateway saw it (``X-Client-IP``), for per-address limits such as the OTP's.

    Only the gateway reaches these services (a NetworkPolicy on EKS), so the header is the gateway's word; a value
    that is not an address is ignored."""
    value = (request.headers.get("x-client-ip") or "").strip()
    return value if value and len(value) <= 45 and all(c in "0123456789abcdefABCDEF.:" for c in value) else None
