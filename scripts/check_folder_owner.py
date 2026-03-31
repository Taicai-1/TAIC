# check_folder_owner.py
from google.oauth2 import service_account
from googleapiclient.discovery import build
import json, sys, traceback

KEYFILE = "agent-52-sa.json"
FOLDER_ID = "15tSzgee4yzhonEHTNIK67279AIRc0yRO"  # ton dossier

def main():
    try:
        with open(KEYFILE, "r", encoding="utf-8-sig") as f:
            info = json.load(f)
        print("Using service account:", info.get("client_email"))
        creds = service_account.Credentials.from_service_account_info(info, scopes=["https://www.googleapis.com/auth/drive"])
        drive = build("drive", "v3", credentials=creds)

        meta = drive.files().get(fileId=FOLDER_ID, fields="id, name, owners, permissions").execute()
        print("Folder metadata:", json.dumps(meta, indent=2))
    except Exception as e:
        print("ERROR:", type(e).__name__, e)
        traceback.print_exc()
        sys.exit(1)

if __name__ == '__main__':
    main()