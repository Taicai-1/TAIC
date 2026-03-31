#!/usr/bin/env python3
"""
Script pour ajouter la colonne agent_id à la table documents
"""
import sys
import os

# Ajouter le répertoire parent au PATH pour les imports
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from database import engine
from sqlalchemy import text

def add_agent_id_column():
    """Ajoute la colonne agent_id à la table documents si elle n'existe pas"""
    try:
        print("Connexion à la base de données PostgreSQL...")
        
        with engine.connect() as conn:
            # Vérifier si la colonne agent_id existe déjà
            result = conn.execute(text("""
                SELECT column_name 
                FROM information_schema.columns 
                WHERE table_name = 'documents' AND column_name = 'agent_id'
            """))
            
            if result.fetchone():
                print("✅ La colonne 'agent_id' existe déjà dans la table 'documents'")
                return True
            
            print("⚠️  La colonne 'agent_id' n'existe pas. Ajout en cours...")
            
            # Ajouter la colonne agent_id
            conn.execute(text("""
                ALTER TABLE documents 
                ADD COLUMN agent_id INTEGER REFERENCES agents(id)
            """))
            
            # Valider la transaction
            conn.commit()
            
            print("✅ Colonne 'agent_id' ajoutée avec succès à la table 'documents'")
            
            # Vérifier que la colonne a été ajoutée
            result = conn.execute(text("""
                SELECT column_name, data_type, is_nullable
                FROM information_schema.columns 
                WHERE table_name = 'documents' AND column_name = 'agent_id'
            """))
            
            row = result.fetchone()
            if row:
                print(f"📋 Détails de la colonne: {row[0]} ({row[1]}, {'NULL' if row[2] == 'YES' else 'NOT NULL'})")
                return True
            else:
                print("❌ Erreur: La colonne n'a pas été créée correctement")
                return False
            
    except Exception as e:
        print(f"❌ Erreur lors de l'ajout de la colonne: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = add_agent_id_column()
    if success:
        print("\n🎉 Migration terminée avec succès!")
    else:
        print("\n💥 Échec de la migration")
        sys.exit(1)
