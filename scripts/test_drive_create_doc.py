# test_drive_create_doc.py
from google.oauth2 import service_account
from googleapiclient.discovery import build
import json, sys, traceback

KEYFILE = "agent-52-sa.json"

def main():
    try:
        with open(KEYFILE, "r", encoding="utf-8-sig") as f:
            info = json.load(f)
        print("Using service account:", info.get("client_email"))
        creds = service_account.Credentials.from_service_account_info(info, scopes=["https://www.googleapis.com/auth/drive"])
        drive = build("drive", "v3", credentials=creds)

        body = {
            "name": "Test Doc created via Drive API",
            "mimeType": "application/vnd.google-apps.document"
        }
        created = drive.files().create(body=body, fields="id").execute()
        fid = created.get("id")
        print("Created file id:", fid)

        meta = drive.files().get(fileId=fid, fields="id, name, mimeType, webViewLink").execute()
        print("Drive metadata:", json.dumps(meta, indent=2))
    except Exception as e:
        print("ERROR:", type(e).__name__, str(e))
        traceback.print_exc()
        sys.exit(1)

if __name__ == '__main__':
    main()