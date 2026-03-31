# test_create_doc.py (tolérant BOM)
from google.oauth2 import service_account
from googleapiclient.discovery import build
import json

KEYFILE = "agent-52-sa.json"

def main():
    try:
        scopes = [
            "https://www.googleapis.com/auth/drive",
            "https://www.googleapis.com/auth/documents"
        ]
        # Lire en utf-8-sig pour enlever automatiquement le BOM si présent
        with open(KEYFILE, "r", encoding="utf-8-sig") as f:
            info = json.load(f)

        creds = service_account.Credentials.from_service_account_info(info, scopes=scopes)
        docs = build("docs", "v1", credentials=creds)
        drive = build("drive", "v3", credentials=creds)

        doc = docs.documents().create(body={"title":"Test from SA (no folder)"}).execute()
        print("Created doc id:", doc.get("documentId"))

        meta = drive.files().get(fileId=doc["documentId"], fields="id, name, webViewLink").execute()
        print("Drive metadata:", json.dumps(meta, indent=2))
    except Exception as e:
        print("ERROR:", type(e).__name__, str(e))
        raise

if __name__ == "__main__":
    main()