# test_create_doc_verbose_error.py
from google.oauth2 import service_account
from googleapiclient.discovery import build
import json, traceback

KEYFILE = "agent-52-sa.json"

def main():
    with open(KEYFILE, "r", encoding="utf-8-sig") as f:
        info = json.load(f)
    creds = service_account.Credentials.from_service_account_info(info, scopes=[
        "https://www.googleapis.com/auth/documents",
        "https://www.googleapis.com/auth/drive"
    ])
    docs = build("docs", "v1", credentials=creds)
    try:
        doc = docs.documents().create(body={"title":"Test verbose error"}).execute()
        print("Created doc id:", doc.get("documentId"))
    except Exception as e:
        print("EXCEPTION TYPE:", type(e).__name__)
        try:
            # googleapiclient.errors.HttpError has .resp and .content
            content = getattr(e, "content", None)
            if content:
                try:
                    decoded = content.decode("utf-8")
                except Exception:
                    decoded = str(content)
                print("e.content:", decoded)
            else:
                print("No e.content available; str(e):", str(e))
        except Exception as inner:
            print("Failed to read e.content:", inner)
        traceback.print_exc()

if __name__ == "__main__":
    main()