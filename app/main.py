from fastapi import FastAPI
from app.database import create_db_and_tables, create_initial_admin
from app.routers.players import router as players_router
from app.routers.auth import router as auth_router
from app.routers.targets import router as targets_router
from app.routers.games import router as games_router

import logging
import app.models
# Create database tables on startup (when the app starts)
app = FastAPI()

#config du logger:
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s", # Format date et heure
    handlers=[
        logging.FileHandler("api.log"), # écrit logs dans ce fichier
        logging.StreamHandler()         # Affiche aussi logs dans console 
    ]
)

#creation objet logger qu'on utilise:
logger = logging.getLogger(__name__)

@app.on_event("startup")
def on_startup():
    logger.info("Démarrage de l'API Dartsify...")
    create_db_and_tables()
    logger.info("Base de données et tables prêtes.")
    create_initial_admin()
    logger.info("L'admin a bien été créé au démarrage ")


app.include_router(players_router) #mettre le /docs a la fin de l'url
app.include_router(auth_router)
app.include_router(targets_router)
app.include_router(games_router)

#Test dans env (fastapi-test et taper : uvicorn app.main:app --reload)
@app.get("/")
def root():
    return {"message": "API is running "}

