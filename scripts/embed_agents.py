import os
import sys
import json
from database import SessionLocal, Agent
from main import update_agent_embedding

# Optionally set your OpenAI API key here
openai_api_key = os.getenv("OPENAI_API_KEY")
if not openai_api_key:
    print("Attention : la variable d'environnement OPENAI_API_KEY n'est pas définie.")
    print("Définissez-la avant d'exécuter ce script.")
    sys.exit(1)
import openai
openai.api_key = openai_api_key

def main():
    db = SessionLocal()
    agents = db.query(Agent).filter(Agent.contexte != None).all()
    count = 0
    for agent in agents:
        if agent.contexte.strip():
            print(f"Embedding agent {agent.id} ({agent.name})...")
            update_agent_embedding(agent, db)
            count += 1
    print(f"Embeddings générés pour {count} agents.")
    db.close()

if __name__ == "__main__":
    main()
