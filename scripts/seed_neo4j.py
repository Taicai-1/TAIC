"""
Script de seed Neo4j AuraDB - Structure entreprise TAIC
Execute: python scripts/seed_neo4j.py --company-id 1
"""

import os
import sys
import argparse
from neo4j import GraphDatabase

# Credentials from env vars (no hardcode)
URI = os.getenv("NEO4J_URI", "")
USER = os.getenv("NEO4J_USER", "neo4j")
PASSWORD = os.getenv("NEO4J_PASSWORD", "")


def seed(tx, company_id):
    # ==============================================
    # 1. NETTOYAGE des noeuds de cette company
    # ==============================================
    tx.run("MATCH (n {company_id: $cid}) DETACH DELETE n", cid=company_id)

    # ==============================================
    # 2. ENTREPRISE
    # ==============================================
    tx.run("""
        CREATE (taic:Company {
            name: 'TAIC',
            type: 'Startup',
            sector: 'SaaS / IA',
            description: 'Plateforme SaaS B2B de chatbots IA entreprise bases sur du RAG',
            founded: 2024,
            stage: 'Early-stage',
            company_id: $cid
        })
    """, cid=company_id)

    # ==============================================
    # 3. PERSONNES
    # ==============================================
    tx.run("""
        CREATE (karim:Person {
            name: 'Karim',
            role: 'CEO',
            department: 'Direction',
            skills: ['Strategy', 'Business Development', 'Fundraising', 'Product Vision', 'Supervision technique'],
            description: 'Co-fondateur et CEO. Supervise toutes les operations, focus sur la levee de fonds et la vente produit. Implique dans les decisions techniques.',
            company_id: $cid
        })
        CREATE (jeremy:Person {
            name: 'Jeremy',
            role: 'CTO',
            department: 'Technique',
            skills: ['Developpement', 'Architecture', 'FastAPI', 'Next.js', 'Cloud GCP', 'IA/RAG'],
            description: 'Co-fondateur et CTO. Responsable de tout le developpement technique, architecture, features. Explique les features a Joshua pour la communication.',
            company_id: $cid
        })
        CREATE (jb:Person {
            name: 'JB',
            role: 'Sales',
            department: 'Commercial',
            skills: ['Vente', 'Negociation', 'Relations clients', 'Pitch', 'Fundraising'],
            description: 'Responsable commercial. Focus sur les rendez-vous de vente et de levee de fonds avec Karim.',
            company_id: $cid
        })
        CREATE (joshua:Person {
            name: 'Joshua',
            role: 'Communication & Reseaux',
            department: 'Communication',
            skills: ['Reseaux sociaux', 'Redaction articles', 'Community management', 'Communication digitale'],
            description: 'Responsable communication et reseaux sociaux. Redige les articles bases sur les features expliquees par Jeremy. Supervise par Karim.',
            company_id: $cid
        })
    """, cid=company_id)

    # ==============================================
    # 4. PRODUIT
    # ==============================================
    tx.run("""
        CREATE (companion:Product {
            name: 'TAIC Companion',
            type: 'SaaS Platform',
            description: 'Plateforme de creation de chatbots IA entreprise avec RAG, multi-LLM, teams, integrations Slack/Email',
            tech_stack: ['FastAPI', 'Next.js', 'PostgreSQL', 'Redis', 'OpenAI', 'Mistral', 'Gemini', 'GCP Cloud Run'],
            company_id: $cid
        })
    """, cid=company_id)

    # ==============================================
    # 5. DOMAINES D'ACTIVITE
    # ==============================================
    tx.run("""
        CREATE (dev:Activity {
            name: 'Developpement technique',
            type: 'Technique',
            description: 'Developpement de features, code backend/frontend, architecture, deploiement',
            company_id: $cid
        })
        CREATE (produit:Activity {
            name: 'Strategie produit',
            type: 'Produit',
            description: 'Reflexion sur utilite des features, roadmap, UX, besoins utilisateurs',
            company_id: $cid
        })
        CREATE (comm:Activity {
            name: 'Communication',
            type: 'Communication',
            description: 'Redaction articles, gestion reseaux sociaux, creation de contenu',
            company_id: $cid
        })
        CREATE (sales:Activity {
            name: 'Vente & Business Dev',
            type: 'Commercial',
            description: 'Rendez-vous clients, demos, negociations commerciales',
            company_id: $cid
        })
        CREATE (fundraising:Activity {
            name: 'Levee de fonds',
            type: 'Finance',
            description: 'Rendez-vous investisseurs, pitch, negociation termes',
            company_id: $cid
        })
    """, cid=company_id)

    # ==============================================
    # 6. PROCESSUS / WORKFLOWS
    # ==============================================
    tx.run("""
        CREATE (meetFeatures:Process {
            name: 'Meetings Features -> Articles',
            type: 'Workflow',
            description: 'Jeremy explique les features techniques a Joshua, qui redige des articles de communication. Karim supervise le processus.',
            frequency: 'Regulier',
            company_id: $cid
        })
        CREATE (rdvBusiness:Process {
            name: 'Rendez-vous Business',
            type: 'Workflow',
            description: 'Karim et JB gerent les rendez-vous, que ce soit pour lever des fonds ou vendre le produit.',
            frequency: 'Quotidien',
            company_id: $cid
        })
    """, cid=company_id)

    # ==============================================
    # 7. RELATIONS
    # ==============================================

    # -- Personnes -> Entreprise --
    tx.run("""
        MATCH (karim:Person {name: 'Karim', company_id: $cid}), (taic:Company {name: 'TAIC', company_id: $cid})
        CREATE (karim)-[:WORKS_AT {role: 'CEO', cofondateur: true}]->(taic)
    """, cid=company_id)
    tx.run("""
        MATCH (jeremy:Person {name: 'Jeremy', company_id: $cid}), (taic:Company {name: 'TAIC', company_id: $cid})
        CREATE (jeremy)-[:WORKS_AT {role: 'CTO', cofondateur: true}]->(taic)
    """, cid=company_id)
    tx.run("""
        MATCH (jb:Person {name: 'JB', company_id: $cid}), (taic:Company {name: 'TAIC', company_id: $cid})
        CREATE (jb)-[:WORKS_AT {role: 'Sales'}]->(taic)
    """, cid=company_id)
    tx.run("""
        MATCH (joshua:Person {name: 'Joshua', company_id: $cid}), (taic:Company {name: 'TAIC', company_id: $cid})
        CREATE (joshua)-[:WORKS_AT {role: 'Communication & Reseaux'}]->(taic)
    """, cid=company_id)

    # -- Hierarchie --
    tx.run("""
        MATCH (karim:Person {name: 'Karim', company_id: $cid}), (jeremy:Person {name: 'Jeremy', company_id: $cid})
        CREATE (karim)-[:SUPERVISE {scope: 'Decisions techniques et strategiques'}]->(jeremy)
    """, cid=company_id)
    tx.run("""
        MATCH (karim:Person {name: 'Karim', company_id: $cid}), (jb:Person {name: 'JB', company_id: $cid})
        CREATE (karim)-[:SUPERVISE {scope: 'Strategie commerciale et fundraising'}]->(jb)
    """, cid=company_id)
    tx.run("""
        MATCH (karim:Person {name: 'Karim', company_id: $cid}), (joshua:Person {name: 'Joshua', company_id: $cid})
        CREATE (karim)-[:SUPERVISE {scope: 'Communication et contenu'}]->(joshua)
    """, cid=company_id)

    # -- Personnes -> Activites --
    tx.run("""
        MATCH (karim:Person {name: 'Karim', company_id: $cid}), (dev:Activity {name: 'Developpement technique', company_id: $cid})
        CREATE (karim)-[:PARTICIPE_A {niveau: 'Supervision et decisions'}]->(dev)
    """, cid=company_id)
    tx.run("""
        MATCH (jeremy:Person {name: 'Jeremy', company_id: $cid}), (dev:Activity {name: 'Developpement technique', company_id: $cid})
        CREATE (jeremy)-[:RESPONSABLE_DE {niveau: 'Lead technique, implementation'}]->(dev)
    """, cid=company_id)
    tx.run("""
        MATCH (karim:Person {name: 'Karim', company_id: $cid}), (produit:Activity {name: 'Strategie produit', company_id: $cid})
        CREATE (karim)-[:PARTICIPE_A]->(produit)
    """, cid=company_id)
    tx.run("""
        MATCH (jeremy:Person {name: 'Jeremy', company_id: $cid}), (produit:Activity {name: 'Strategie produit', company_id: $cid})
        CREATE (jeremy)-[:PARTICIPE_A]->(produit)
    """, cid=company_id)
    tx.run("""
        MATCH (jb:Person {name: 'JB', company_id: $cid}), (produit:Activity {name: 'Strategie produit', company_id: $cid})
        CREATE (jb)-[:PARTICIPE_A]->(produit)
    """, cid=company_id)
    tx.run("""
        MATCH (joshua:Person {name: 'Joshua', company_id: $cid}), (produit:Activity {name: 'Strategie produit', company_id: $cid})
        CREATE (joshua)-[:PARTICIPE_A]->(produit)
    """, cid=company_id)
    tx.run("""
        MATCH (joshua:Person {name: 'Joshua', company_id: $cid}), (comm:Activity {name: 'Communication', company_id: $cid})
        CREATE (joshua)-[:RESPONSABLE_DE]->(comm)
    """, cid=company_id)
    tx.run("""
        MATCH (jb:Person {name: 'JB', company_id: $cid}), (sales:Activity {name: 'Vente & Business Dev', company_id: $cid})
        CREATE (jb)-[:RESPONSABLE_DE]->(sales)
    """, cid=company_id)
    tx.run("""
        MATCH (karim:Person {name: 'Karim', company_id: $cid}), (sales:Activity {name: 'Vente & Business Dev', company_id: $cid})
        CREATE (karim)-[:PARTICIPE_A {niveau: 'Rendez-vous cles'}]->(sales)
    """, cid=company_id)
    tx.run("""
        MATCH (karim:Person {name: 'Karim', company_id: $cid}), (fundraising:Activity {name: 'Levee de fonds', company_id: $cid})
        CREATE (karim)-[:RESPONSABLE_DE]->(fundraising)
    """, cid=company_id)
    tx.run("""
        MATCH (jb:Person {name: 'JB', company_id: $cid}), (fundraising:Activity {name: 'Levee de fonds', company_id: $cid})
        CREATE (jb)-[:PARTICIPE_A {niveau: 'Rendez-vous investisseurs'}]->(fundraising)
    """, cid=company_id)

    # -- Entreprise -> Produit --
    tx.run("""
        MATCH (taic:Company {name: 'TAIC', company_id: $cid}), (companion:Product {name: 'TAIC Companion', company_id: $cid})
        CREATE (taic)-[:DEVELOPPE]->(companion)
    """, cid=company_id)

    # -- Personnes -> Processus --
    tx.run("""
        MATCH (jeremy:Person {name: 'Jeremy', company_id: $cid}), (meet:Process {name: 'Meetings Features -> Articles', company_id: $cid})
        CREATE (jeremy)-[:PARTICIPE_A {role: 'Explique les features techniques'}]->(meet)
    """, cid=company_id)
    tx.run("""
        MATCH (joshua:Person {name: 'Joshua', company_id: $cid}), (meet:Process {name: 'Meetings Features -> Articles', company_id: $cid})
        CREATE (joshua)-[:PARTICIPE_A {role: 'Redige les articles'}]->(meet)
    """, cid=company_id)
    tx.run("""
        MATCH (karim:Person {name: 'Karim', company_id: $cid}), (meet:Process {name: 'Meetings Features -> Articles', company_id: $cid})
        CREATE (karim)-[:SUPERVISE {role: 'Validation et supervision'}]->(meet)
    """, cid=company_id)
    tx.run("""
        MATCH (karim:Person {name: 'Karim', company_id: $cid}), (rdv:Process {name: 'Rendez-vous Business', company_id: $cid})
        CREATE (karim)-[:PARTICIPE_A {role: 'Lead des rendez-vous'}]->(rdv)
    """, cid=company_id)
    tx.run("""
        MATCH (jb:Person {name: 'JB', company_id: $cid}), (rdv:Process {name: 'Rendez-vous Business', company_id: $cid})
        CREATE (jb)-[:PARTICIPE_A {role: 'Pitch et negociation'}]->(rdv)
    """, cid=company_id)

    # -- Collaborations directes --
    tx.run("""
        MATCH (jeremy:Person {name: 'Jeremy', company_id: $cid}), (joshua:Person {name: 'Joshua', company_id: $cid})
        CREATE (jeremy)-[:COLLABORE_AVEC {contexte: 'Jeremy explique les features, Joshua redige les articles'}]->(joshua)
    """, cid=company_id)
    tx.run("""
        MATCH (karim:Person {name: 'Karim', company_id: $cid}), (jb:Person {name: 'JB', company_id: $cid})
        CREATE (karim)-[:COLLABORE_AVEC {contexte: 'Rendez-vous levee de fonds et vente produit'}]->(jb)
    """, cid=company_id)
    tx.run("""
        MATCH (karim:Person {name: 'Karim', company_id: $cid}), (jeremy:Person {name: 'Jeremy', company_id: $cid})
        CREATE (karim)-[:COLLABORE_AVEC {contexte: 'Decisions techniques et roadmap produit'}]->(jeremy)
    """, cid=company_id)


def verify(session, company_id):
    """Affiche un resume du graphe cree."""
    print("\n== VERIFICATION DU GRAPHE ==\n")

    # Compteurs
    result = session.run("MATCH (n {company_id: $cid}) RETURN labels(n)[0] AS label, count(n) AS count ORDER BY label", cid=company_id)
    print("Noeuds:")
    for record in result:
        print(f"  {record['label']}: {record['count']}")

    result = session.run("MATCH (a {company_id: $cid})-[r]->(b) RETURN type(r) AS type, count(r) AS count ORDER BY count DESC", cid=company_id)
    print("\nRelations:")
    for record in result:
        print(f"  {record['type']}: {record['count']}")

    # Afficher les personnes et leurs roles
    print("\n-- Equipe TAIC --")
    result = session.run("""
        MATCH (p:Person {company_id: $cid})-[w:WORKS_AT]->(c:Company {company_id: $cid})
        RETURN p.name AS nom, w.role AS role,
               CASE WHEN w.cofondateur = true THEN 'Co-fondateur' ELSE '' END AS statut
        ORDER BY p.name
    """, cid=company_id)
    for record in result:
        statut = f" ({record['statut']})" if record['statut'] else ""
        print(f"  {record['nom']} - {record['role']}{statut}")

    print(f"\n[OK] Seed complete pour company_id={company_id}.")
    print("  Requete pour tout voir: MATCH (n {company_id: " + str(company_id) + "})-[r]->(m) RETURN n, r, m")


def main():
    parser = argparse.ArgumentParser(description="Seed Neo4j AuraDB with company data")
    parser.add_argument("--company-id", type=int, required=True, help="PostgreSQL company ID to tag nodes with")
    args = parser.parse_args()

    if not URI or not PASSWORD:
        print("ERROR: NEO4J_URI and NEO4J_PASSWORD environment variables must be set")
        sys.exit(1)

    print(f"Connexion a Neo4j AuraDB ({URI})...")
    driver = GraphDatabase.driver(URI, auth=(USER, PASSWORD))
    driver.verify_connectivity()
    print("[OK] Connecte\n")

    print(f"Seed de la base pour company_id={args.company_id}...")
    with driver.session() as session:
        session.execute_write(seed, args.company_id)
        print("[OK] Donnees inserees")
        verify(session, args.company_id)

    driver.close()


if __name__ == "__main__":
    main()
