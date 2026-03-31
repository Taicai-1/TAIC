# test_drive_create_doc_with_content.py
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
import io, json

KEYFILE = "agent-52-sa.json"  # ta clé locale
TITLE = "Test doc via Drive-convert"
HTML_CONTENT = "<html><body><h1>Biographie d'Einstein</h1><p>Albert Einstein est né en 1879...</p></body></html>"

def main():
    with open(KEYFILE, "r", encoding="utf-8-sig") as f:
        info = json.load(f)
    creds = service_account.Credentials.from_service_account_info(info, scopes=["https://www.googleapis.com/auth/drive"])
    drive = build("drive", "v3", credentials=creds)

    # Prépare l'upload en HTML et demande la conversion en Google Docs
    fh = io.BytesIO(HTML_CONTENT.encode("utf-8"))
    media = MediaIoBaseUpload(fh, mimetype="text/html", resumable=False)

    metadata = {
        "name": TITLE,
        # IMPORTANT: to create a Google Docs file, set the target mimeType to Google Docs in metadata
        "mimeType": "application/vnd.google-apps.document",
        # optionally put parents: ["YOUR_FOLDER_ID"]
    }

    try:
        created = drive.files().create(body=metadata, media_body=media, supportsAllDrives=True, fields="id, webViewLink").execute()
        print("Created file id:", created.get("id"))
        print("webViewLink:", created.get("webViewLink"))
    except Exception as e:
        print("ERROR:", type(e).__name__, e)
        # print full details if HttpError
        try:
            content = getattr(e, "content", None)
            if content:
                print("e.content:", content.decode("utf-8") if isinstance(content, (bytes, bytearray)) else content)
        except Exception:
            pass
        raise

if __name__ == "__main__":
    main()