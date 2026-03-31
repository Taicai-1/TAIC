import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from database import User, get_database_url
from auth import hash_password

EMAIL = input("Email de l'utilisateur à réinitialiser : ")
NEW_PASSWORD = "557Karim!"

engine = create_engine(get_database_url())
Session = sessionmaker(bind=engine)
session = Session()

user = session.query(User).filter(User.email == EMAIL).first()
if not user:
    print(f"❌ Utilisateur avec email {EMAIL} introuvable.")
else:
    user.hashed_password = hash_password(NEW_PASSWORD)
    session.commit()
    print(f"✅ Mot de passe réinitialisé pour {EMAIL}.")
session.close()
