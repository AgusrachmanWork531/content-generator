from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse
import logging
from app.services.google_auth import get_auth_url, exchange_code, is_authenticated

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])


@router.get("/google")
async def google_login():
    """Redirect user to Google OAuth2 consent screen."""
    try:
        auth_url = get_auth_url()
        return RedirectResponse(url=auth_url)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to generate auth URL: {e}")


@router.get("/google/callback")
async def google_callback(request: Request):
    """Handle OAuth2 callback and save tokens."""
    try:
        # Pass the full URL to correctly handle PKCE (code_verifier)
        exchange_code(str(request.url))
        return {"status": "success", "message": "Google account connected successfully."}
    except Exception as e:
        logger.error(f"OAuth callback error: {e}")
        raise HTTPException(status_code=500, detail=f"OAuth failed: {e}")


@router.get("/status")
async def auth_status():
    """Check if user is authenticated with Google."""
    authenticated = is_authenticated()
    return {
        "authenticated": authenticated,
        "message": "Connected" if authenticated else "Not connected. Visit /auth/google to connect.",
    }
