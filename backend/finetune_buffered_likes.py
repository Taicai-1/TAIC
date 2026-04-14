import os
from dotenv import load_dotenv

os.environ["LANG"] = "en_US.UTF-8"
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), ".env"))
import json
import psycopg2
import openai


# Paramètres
def get_env(var, default=None):
    v = os.getenv(var)
    if v is None:
        if default is not None:
            return default
        raise RuntimeError(f"Missing env var: {var}")
    return v


BUFFER_THRESHOLD = 10  # Nombre de paires avant fine-tuning
DB_URL = get_env("DATABASE_URL")
OPENAI_API_KEY = get_env("OPENAI_API_KEY")
MODEL_NAME = "gpt-3.5-turbo"

# 1. Connexion à la base
conn = psycopg2.connect(DB_URL)
cur = conn.cursor()

# 2. Récupérer tous les agent_id
cur.execute("SELECT id FROM agents")
agent_ids = [row[0] for row in cur.fetchall()]

for agent_id in agent_ids:
    # 3. Récupérer les paires question/réponse likées et bufferisées pour cet agent
    cur.execute(
        """
        SELECT m1.content as question, m2.content as answer, m1.id as user_id, m2.id as agent_msg_id
        FROM messages m1
        JOIN messages m2 ON m1.conversation_id = m2.conversation_id
            AND m1.role = 'user' AND m2.role = 'agent'
            AND m1.timestamp < m2.timestamp
        JOIN conversations c ON m1.conversation_id = c.id
        WHERE m1.feedback = 'like' AND m2.feedback = 'like'
          AND m1.buffered = 1 AND m2.buffered = 1
          AND c.agent_id = %s
        ORDER BY m2.timestamp ASC
    """,
        (agent_id,),
    )
    pairs = cur.fetchall()

    if len(pairs) < BUFFER_THRESHOLD:
        print(f"Agent {agent_id}: Pas assez de paires pour fine-tuning ({len(pairs)}/{BUFFER_THRESHOLD})")
        continue

    jsonl_path = f"finetune_data_agent_{agent_id}.jsonl"
    with open(jsonl_path, "w", encoding="utf-8") as f:
        for question, answer, _, _ in pairs:
            obj = {"messages": [{"role": "user", "content": question}, {"role": "assistant", "content": answer}]}
            f.write(json.dumps(obj, ensure_ascii=False) + "\n")

    openai.api_key = OPENAI_API_KEY
    file_resp = openai.files.create(file=open(jsonl_path, "rb"), purpose="fine-tune")
    file_id = file_resp.id

    job = openai.fine_tuning.jobs.create(training_file=file_id, model=MODEL_NAME)
    print(f"Agent {agent_id}: Fine-tuning lancé : job_id={job.id}")

    # Stocke l'ID du modèle fine-tuné dans la table agents (sera vide tant que le job n'est pas terminé)
    # On peut stocker l'ID du job pour suivi, ou automatiser la mise à jour plus tard
    cur.execute("UPDATE agents SET finetuned_model_id = %s WHERE id = %s", (job.id, agent_id))
    conn.commit()

    # 5. Marquer les paires comme traitées (buffered=0)
    user_ids = [row[2] for row in pairs]
    agent_msg_ids = [row[3] for row in pairs]
    all_ids = user_ids + agent_msg_ids
    placeholders = ",".join(["%s"] * len(all_ids))
    cur.execute(f"UPDATE messages SET buffered=0 WHERE id IN ({placeholders})", all_ids)
    conn.commit()
    print(f"Agent {agent_id}: Buffer vidé et prêt pour de nouveaux likes.")

cur.close()
conn.close()
