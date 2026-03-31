import os
from dotenv import load_dotenv
import psycopg2
import openai

# Charger les variables d'environnement
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), ".env"))
DB_URL = os.getenv("DATABASE_URL")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
openai.api_key = OPENAI_API_KEY

# Connexion à la base
conn = psycopg2.connect(DB_URL)
cur = conn.cursor()

# Récupérer tous les agents avec un job de fine-tuning en cours (ftjob-...)
cur.execute("SELECT id, finetuned_model_id FROM agents WHERE finetuned_model_id LIKE 'ftjob-%'")
rows = cur.fetchall()


for agent_id, job_id in rows:
    try:
        job = openai.fine_tuning.jobs.retrieve(job_id)
        if job.status == "succeeded" and job.fine_tuned_model:
            # Met à jour la colonne avec l'ID du modèle fine-tuné
            cur.execute(
                "UPDATE agents SET finetuned_model_id = %s WHERE id = %s",
                (job.fine_tuned_model, agent_id)
            )
            conn.commit()
            print(f"Agent {agent_id}: Job terminé, colonne mise à jour avec le modèle : {job.fine_tuned_model}")
        else:
            print(f"Agent {agent_id}: Job non terminé (status = {job.status})")
    except Exception as e:
        print(f"Agent {agent_id}: Erreur lors de la récupération du job {job_id} : {e}")

cur.close()
conn.close()

