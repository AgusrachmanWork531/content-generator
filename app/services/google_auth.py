import os
import json
import logging
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from google.auth.transport.requests import Request
from google.auth.exceptions import RefreshError

# Allow insecure transport for local development (http://localhost)
os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'

logger = logging.getLogger(__name__)

CLIENT_SECRET_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "client-secret.json")
TOKEN_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "token.json")
SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly",
    "https://www.googleapis.com/auth/spreadsheets",
]
REDIRECT_URI = "http://localhost:8888/auth/google/callback"

# Store Flow object in memory so code_verifier persists between auth and callback
_active_flow = None


def get_auth_url() -> str:
    """Generate Google OAuth2 consent URL."""
    global _active_flow
    _active_flow = Flow.from_client_secrets_file(CLIENT_SECRET_FILE, scopes=SCOPES)
    _active_flow.redirect_uri = REDIRECT_URI
    auth_url, _ = _active_flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
    )
    return auth_url


def exchange_code(authorization_response: str) -> dict:
    """Exchange authorization response URL for tokens and save to token.json."""
    global _active_flow
    if _active_flow is None:
        raise Exception("No active auth flow. Please visit /auth/google first.")
    
    # This automatically handles the code, state, and code_verifier (PKCE)
    _active_flow.fetch_token(authorization_response=authorization_response)

    creds = _active_flow.credentials
    token_data = {
        "token": creds.token,
        "refresh_token": creds.refresh_token,
        "token_uri": creds.token_uri,
        "client_id": creds.client_id,
        "client_secret": creds.client_secret,
        "scopes": creds.scopes,
    }

    with open(TOKEN_FILE, "w") as f:
        json.dump(token_data, f, indent=2, default=list)

    logger.info("OAuth tokens saved to token.json")
    return token_data


def get_credentials() -> Credentials:
    """Load credentials from token.json. Auto-refresh if expired."""
    if not os.path.exists(TOKEN_FILE):
        raise Exception("Not authenticated. Please visit /auth/google first.")

    with open(TOKEN_FILE, "r") as f:
        token_data = json.load(f)

    creds = Credentials(
        token=token_data["token"],
        refresh_token=token_data.get("refresh_token"),
        token_uri=token_data["token_uri"],
        client_id=token_data["client_id"],
        client_secret=token_data["client_secret"],
        scopes=token_data.get("scopes"),
    )

    if creds.expired and creds.refresh_token:
        logger.info("Refreshing expired token...")
        try:
            creds.refresh(Request())
            # Update saved token
            token_data["token"] = creds.token
            with open(TOKEN_FILE, "w") as f:
                json.dump(token_data, f, indent=2, default=list)
            logger.info("Token refreshed and saved successfully.")
        except RefreshError as e:
            logger.error(f"Failed to refresh token (Revoked or Expired): {e}")
            if os.path.exists(TOKEN_FILE):
                os.remove(TOKEN_FILE)
                logger.warning(f"Deleted invalid {TOKEN_FILE}. Re-authentication required.")
            raise Exception("Authentication session has been revoked or expired. Please visit /auth/google to re-authenticate.")
        except Exception as e:
            logger.error(f"Unexpected error during token refresh: {e}")
            raise Exception(f"OAuth refresh failed: {e}")
 
    return creds


def is_authenticated() -> bool:
    """Check if a valid token exists."""
    try:
        creds = get_credentials()
        return creds.valid or (creds.expired and creds.refresh_token is not None)
    except Exception:
        return False
