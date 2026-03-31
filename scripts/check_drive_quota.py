# check_drive_quota.py
from google.oauth2 import service_account
from googleapiclient.discovery import build
import json

KEYFILE = "agent-52-sa.json"

with open(KEYFILE, "r", encoding="utf-8-sig") as f:
    info = json.load(f)
creds = service_account.Credentials.from_service_account_info(info, scopes=["https://www.googleapis.com/auth/drive.metadata.readonly"])
drive = build("drive", "v3", credentials=creds)
about = drive.about().get(fields="user, storageQuota").execute()
import pprint
pprint.pprint(about)