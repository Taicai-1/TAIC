import os
import httpx

API_KEY = os.getenv("OPENAI_API_KEY")
if not API_KEY:
    print("OPENAI_API_KEY non défini dans l'environnement.")
    exit(1)

headers = {"Authorization": f"Bearer {API_KEY}"}
url = "https://api.openai.com/v1/embeddings"
payload = {"input": ["test embedding"], "model": "text-embedding-ada-002"}

try:
    response = httpx.post(url, headers=headers, json=payload, timeout=10)
    print(f"Status: {response.status_code}")
    print(f"Body: {response.text[:500]}")
except Exception as e:
    print(f"Erreur de connexion: {e}")
