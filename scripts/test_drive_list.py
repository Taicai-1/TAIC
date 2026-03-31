# test_drive_list_verbose.py
from google.oauth2 import service_account
from googleapiclient.discovery import build
import json, sys, traceback

KEYFILE = "agent-52-sa.json"

def main():
    try:
        with open(KEYFILE, "r", encoding="utf-8-sig") as f:
            info = json.load(f)
        print("Loaded service account, client_email:", info.get("client_email"))
        creds = service_account.Credentials.from_service_account_info(info, scopes=["https://www.googleapis.com/auth/drive"])
        drive = build("drive", "v3", credentials=creds)

        res = drive.files().list(pageSize=5).execute()
        print("OK, files list result (raw):")
        print(json.dumps(res, indent=2))
    except Exception as e:
        print("ERROR:", type(e).__name__, str(e))
        traceback.print_exc()
        sys.exit(1)

if __name__ == '__main__':
    main()