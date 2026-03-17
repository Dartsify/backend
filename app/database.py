from sqlmodel import SQLModel, create_engine, Session, select
from fastapi import Depends
from typing import Annotated

#pour creation de l'admin
from app.config import ADMIN_NAME, ADMIN_USERNAME, ADMIN_PASSWORD, ADMIN_EMAIL

#Create engine (what holds the connection with db)
sqlite_file_name = "database.db"
sqlite_url = f"sqlite:///{sqlite_file_name}"

connect_args = {"check_same_thread": False}# allows FastAPI to use the same SQLite database in diff threads (necessary)
engine = create_engine(sqlite_url, connect_args=connect_args)

#Create tables
def create_db_and_tables():
    SQLModel.metadata.create_all(engine)

# Create Session dependency -> session is what stores the objects in memory and keeps track of any changes (then uses the engine to communicate with the database and save the changes)
def get_session():
    with Session(engine) as session:
        yield session


SessionDep = Annotated[Session, Depends(get_session)]

#Creation de l'admin initial
def create_initial_admin():
    # importe les modèles et la sécurité ici pour éviter les fameuses erreurs "d'import circulaire" au démarrage (debug)
    from app.models.player import Player
    from app.security.auth import hash_password

    with Session(engine) as session:
        # On vérifie si admin existe déjà
        admin_user = session.exec(select(Player).where(Player.username == ADMIN_USERNAME)).first()
        
        if not admin_user:
            # Si existe pas, on hache son mot de passe et on le crée
            hashed_pw = hash_password(ADMIN_PASSWORD)
            new_admin = Player(
                username=ADMIN_USERNAME,
                email=ADMIN_EMAIL,
                name=ADMIN_NAME,
                hashed_password=hashed_pw,
                is_admin=True  # badge admin
            )
            session.add(new_admin)
            session.commit()
