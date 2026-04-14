#!/usr/bin/env python3
"""
Script pour créer toutes les tables dans la base de données PostgreSQL
"""

import sys
import os

# Ajouter le répertoire parent au PATH pour les imports
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from database import Base, engine
from sqlalchemy import text


def create_all_tables():
    """Crée toutes les tables définies dans les modèles"""
    try:
        print("Connexion à la base de données PostgreSQL...")

        # Créer toutes les tables définies dans les modèles
        print("Création de toutes les tables...")
        Base.metadata.create_all(bind=engine)

        # Vérifier que les tables ont été créées
        with engine.connect() as conn:
            # Lister toutes les tables
            result = conn.execute(
                text("""
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = 'public'
                ORDER BY table_name;
            """)
            )
            tables = [row[0] for row in result.fetchall()]

            print("Tables créées:")
            for table in tables:
                print(f"  ✅ {table}")

            # Vérifier spécifiquement la table agents
            if "agents" in tables:
                print("\n✅ Table 'agents' créée avec succès!")

                # Vérifier la structure de la table agents
                result = conn.execute(
                    text("""
                    SELECT column_name, data_type, is_nullable
                    FROM information_schema.columns
                    WHERE table_name = 'agents'
                    ORDER BY ordinal_position;
                """)
                )

                print("Structure de la table 'agents':")
                for row in result.fetchall():
                    print(f"  - {row[0]}: {row[1]} ({'NULL' if row[2] == 'YES' else 'NOT NULL'})")
            else:
                print("❌ Erreur: Table 'agents' non créée")
                return False

            return True

    except Exception as e:
        print(f"❌ Erreur lors de la création des tables: {e}")
        import traceback

        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = create_all_tables()
    if success:
        print("\n🎉 Initialisation de la base de données terminée avec succès!")
    else:
        print("\n💥 Échec de l'initialisation de la base de données")
        sys.exit(1)
