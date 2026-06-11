import os
import json
import webbrowser
from pathlib import Path
from google_auth_oauthlib.flow import Flow
from http.server import HTTPServer, BaseHTTPRequestHandler
import urllib.parse as urlparse

# Set insecure transport for local redirection http
os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"

auth_response_url = None

class OAuthCallbackHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        global auth_response_url
        host = self.headers.get('Host', 'localhost:8888')
        full_url = f"http://{host}{self.path}"
        
        parsed = urlparse.urlparse(full_url)
        if parsed.path == "/auth/google/callback":
            auth_response_url = full_url
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.end_headers()
            self.wfile.write(b"""
            <html>
                <body style="font-family: sans-serif; text-align: center; padding: 50px;">
                    <h1 style="color: #4CAF50;">Otorisasi Berhasil!</h1>
                    <p>Proses otentikasi selesai. Anda dapat menutup halaman ini sekarang.</p>
                </body>
            </html>
            """)
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        # Suppress logging to keep output clean
        return

def main():
    token_path = Path("/Users/agusrachman/Documents/Codex/content-short/token.json")
    if not token_path.exists():
        print(f"Error: {token_path} not found.")
        return

    with open(token_path, "r", encoding="utf-8") as f:
        d = json.load(f)

    # Use the client configuration from token.json
    # Since this is a Web application client ID, we MUST use the exact redirect URI.
    client_config = {
        "web": {
            "client_id": d["client_id"],
            "client_secret": d["client_secret"],
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": d["token_uri"],
        }
    }

    scopes = d.get("scopes", [
        "https://www.googleapis.com/auth/youtube.upload",
        "https://www.googleapis.com/auth/youtube.readonly",
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive.file"
    ])

    flow = Flow.from_client_config(client_config, scopes=scopes)
    
    # Force the specific redirect URI registered in Google Console
    redirect_uri = "http://localhost:8888/auth/google/callback"
    flow.redirect_uri = redirect_uri

    # Generate authorization URL
    authorization_url, state = flow.authorization_url(
        access_type='offline',
        include_granted_scopes='true',
        prompt='consent'  # Force showing consent page to get refresh token
    )

    print("Starting Google OAuth2 authorization flow...")
    print(f"Visit this URL to authorize: {authorization_url}")
    
    # Try opening the browser automatically
    try:
        webbrowser.open(authorization_url)
    except Exception:
        pass

    # Start the server on port 8888
    server = HTTPServer(('127.0.0.1', 8888), OAuthCallbackHandler)
    
    print("Waiting for callback on http://localhost:8888/auth/google/callback ...")
    while auth_response_url is None:
        server.handle_request()
        
    server.server_close()

    # Exchange authorization code for token
    flow.fetch_token(authorization_response=auth_response_url)
    creds = flow.credentials

    updated = {
        "token": creds.token,
        "refresh_token": creds.refresh_token,
        "token_uri": creds.token_uri,
        "client_id": creds.client_id,
        "client_secret": creds.client_secret,
        "scopes": creds.scopes,
    }

    # Write updated token back to disk
    with open(token_path, "w", encoding="utf-8") as f:
        json.dump(updated, f, indent=2)
    print(f"Updated token written to {token_path}")

    # Propagate to download-clip token path
    clip_token_path = Path("/Users/agusrachman/Documents/Docker/n8n/download-clip/token.json")
    if clip_token_path.parent.exists():
        with open(clip_token_path, "w", encoding="utf-8") as f:
            json.dump(updated, f, indent=2)
        print(f"Updated token written to {clip_token_path}")

if __name__ == "__main__":
    main()
