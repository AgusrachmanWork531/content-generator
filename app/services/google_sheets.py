from googleapiclient.discovery import build
import logging
import time
import socket
from typing import List, Dict, Any
from app.services.google_auth import get_credentials

logger = logging.getLogger(__name__)

SPREADSHEET_ID = "1m3iZjW_CfzDdOwDWI4gAK4RX8jybva1OmIQL7Ipmtzo"
RANGE_NAME = "content_mentah!A2:R"  # Expanded to include originality columns Q, R
COMPILATION_RANGE_NAME = "compilation!A2:P"

class GoogleSheetsService:
    def __init__(self):
        self.creds = None
        self.service = None

    def _get_service(self):
        if not self.service:
            self.creds = get_credentials()
            # Set default timeout for the socket
            socket.setdefaulttimeout(60)
            self.service = build('sheets', 'v4', credentials=self.creds, cache_discovery=False)
        return self.service

    def _execute_with_retry(self, request, max_retries=3):
        """Helper to execute API requests with exponential backoff for transient errors."""
        for i in range(max_retries):
            try:
                return request.execute()
            except Exception as e:
                err_msg = str(e)
                # Handle transient network errors (Timeout, Connection Reset, etc.)
                transient_errors = [
                    "[Errno 54]", "[Errno 60]", "Operation timed out", 
                    "Connection reset by peer", "HttpError 500", "HttpError 503"
                ]
                
                if any(err in err_msg for err in transient_errors) and i < max_retries - 1:
                    wait_time = 2 ** (i + 1)
                    logger.warning(f"⚠️ Google Sheets API transient error: {err_msg}. Retrying in {wait_time}s... (Attempt {i+1}/{max_retries})")
                    time.sleep(wait_time)
                    continue
                
                # If it's not a transient error or we're out of retries, raise it
                raise e

    def get_pending_rows(self) -> List[Dict[str, Any]]:
        """
        Fetches rows where Execution is TRUE and Done is empty.
        Returns a list of dicts with row data and their original row index.
        """
        try:
            service = self._get_service()
            sheet = service.spreadsheets()
            request = sheet.values().get(spreadsheetId=SPREADSHEET_ID, range=RANGE_NAME)
            result = self._execute_with_retry(request)
            values = result.get('values', [])

            if not values:
                logger.info("No data found in spreadsheet.")
                return []

            pending = []
            for i, row in enumerate(values):
                # Ensure row has enough columns (up to R = index 17)
                if len(row) < 18:
                    row.extend([''] * (18 - len(row)))

                # A: URL (0), N: Execution (13), O: Done (14), P: Narration (15)
                execution_val = row[13].strip().upper() if len(row) > 13 else "FALSE"
                done_val = row[14].strip().upper() if len(row) > 14 else "FALSE"
                
                # Checkbox logic: 'TRUE' means checked, anything else (FALSE or empty) is unchecked
                execution = (execution_val == 'TRUE')
                is_done = (done_val == 'TRUE')

                if execution and not is_done:
                    pending.append({
                        "row_index": i + 2,
                        "url": row[0],
                        "reframe": row[1].strip().upper() == 'TRUE',
                        "subtitles": row[2].strip().upper() == 'TRUE',
                        "platform": row[3].lower() if row[3] else "youtube",
                        "start_time": row[4] if row[4] else None,
                        "end_time": row[5] if row[5] else None,
                        "upload": row[8].strip().upper() == 'TRUE' if len(row) > 8 else False,
                        "title": row[9] if len(row) > 9 else "",
                        "description": row[10] if len(row) > 10 else "",
                        "tags": row[11] if len(row) > 11 else "",
                        "thumbnail_image": row[12] if len(row) > 12 else "",
                        "narration_text": row[15] if len(row) > 15 else "",
                        "satisfying": row[16].strip().upper() == 'TRUE' if len(row) > 16 else False,
                        "anti_bot": row[17].strip().upper() == 'TRUE' if len(row) > 17 else True, # Default True
                    })
            
            logger.info(f"Found {len(pending)} pending rows for execution.")
            return pending

        except Exception as e:
            logger.error(f"Error reading Google Sheets: {e}")
            
            # Auto-healing: If the token is revoked or expired during an API call, delete it.
            if "invalid_grant" in str(e) or "Token has been expired" in str(e):
                import os
                token_file = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "token.json")
                if os.path.exists(token_file):
                    os.remove(token_file)
                    logger.warning("🚨 Busted Token Detected! Deleted expired token.json.")
                    logger.warning("👉 ACTION REQUIRED: Please visit http://localhost:8888/auth/google in your browser to re-authenticate.")
                
                # Reset service so it attempts fresh login next time
                self.creds = None
                self.service = None
                
            return []

    def get_compilation_pending_rows(self) -> Dict[str, List[Dict[str, Any]]]:
        """
        Fetches rows from 'compilation' sheet where Execution is TRUE and Done is FALSE.
        Groups them by Compilation ID.
        """
        try:
            service = self._get_service()
            sheet = service.spreadsheets()
            request = sheet.values().get(spreadsheetId=SPREADSHEET_ID, range=COMPILATION_RANGE_NAME)
            result = self._execute_with_retry(request)
            values = result.get('values', [])

            if not values:
                logger.info("No data found in compilation sheet.")
                return {}

            compilations = {}
            for i, row in enumerate(values):
                # Ensure row has enough columns (up to P = index 15)
                if len(row) < 16:
                    row.extend([''] * (16 - len(row)))

                comp_id = row[0].strip()
                if not comp_id:
                    continue

                execution = row[7].strip().upper() == 'TRUE'
                done = row[8].strip().upper() == 'TRUE'

                if execution and not done:
                    if comp_id not in compilations:
                        compilations[comp_id] = []
                    
                    compilations[comp_id].append({
                        "row_index": i + 2,
                        "order": int(row[1]) if row[1].isdigit() else 0,
                        "url": row[2],
                        "start_time": row[3] if row[3] else None,
                        "end_time": row[4] if row[4] else None,
                        "bg_music_url": row[5] if row[5] else None,
                        "final_title": row[6],
                        "upload": row[10].lower() == 'true',
                        "yt_title": row[11],       # Column L (11)
                        "yt_description": row[12], # Column M (12)
                        "yt_tags": row[13],        # Column N (13)
                        "subtitles": row[14].strip().upper() == 'TRUE' if len(row) > 14 else False, # Column O
                        "transitions": row[15].strip().upper() == 'TRUE' if len(row) > 15 else False # Column P
                    })
            
            # Sort clips by order for each compilation
            for cid in compilations:
                compilations[cid].sort(key=lambda x: x['order'])
            
            logger.info(f"Found {len(compilations)} pending compilations.")
            return compilations

        except Exception as e:
            logger.error(f"Error reading compilation sheet: {e}")
            return {}

    def mark_as_done(self, row_index: int):
        """
        Updates the 'Done' column (O) to TRUE for the given row index in 'content_mentah'.
        """
        try:
            service = self._get_service()
            sheet = service.spreadsheets()
            range_to_update = f"content_mentah!O{row_index}"
            body = {
                'values': [['TRUE']]
            }
            request = sheet.values().update(
                spreadsheetId=SPREADSHEET_ID,
                range=range_to_update,
                valueInputOption='USER_ENTERED',
                body=body
            )
            self._execute_with_retry(request)
            logger.info(f"Marked row {row_index} as DONE in Google Sheets.")
        except Exception as e:
            logger.error(f"Error updating Google Sheets row {row_index}: {e}")

    def mark_compilation_as_done(self, row_indices: List[int], result_url: str = ""):
        """
        Updates the 'Done' column (I) to TRUE and 'Result URL' (J) for given row indices in 'compilation'.
        """
        try:
            service = self._get_service()
            sheet = service.spreadsheets()
            
            for idx in row_indices:
                range_to_update = f"compilation!I{idx}:J{idx}"
                body = {
                    'values': [['TRUE', result_url]]
                }
                request = sheet.values().update(
                    spreadsheetId=SPREADSHEET_ID,
                    range=range_to_update,
                    valueInputOption='USER_ENTERED',
                    body=body
                )
                self._execute_with_retry(request)
                logger.info(f"Marked compilation row {idx} as DONE.")
        except Exception as e:
            logger.error(f"Error updating compilation rows: {e}")

google_sheets_service = GoogleSheetsService()

def mark_row_done(row_index: int):
    google_sheets_service.mark_as_done(row_index)
