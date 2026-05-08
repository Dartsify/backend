import logging
import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlmodel import Session

import app.models
from app.database import engine, create_db_and_tables, create_initial_admin, seed_test_data, seed_random_games_and_throws
from app.routers.players import router as players_router
from app.routers.auth import router as auth_router
from app.routers.targets import router as targets_router
from app.routers.games import router as games_router
from app.routers.throws import router as throws_router

from app.utils.game_state import cleanup_inactive_games

# config du logger:
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s", # Format date et heure
    datefmt="%H:%M:%S", # Affiche seulement l'heure
    handlers=[
        logging.FileHandler("api.log"), # écrit logs dans ce fichier
        logging.StreamHandler()         # Affiche aussi logs dans console 
    ]
)

# creation objet logger qu'on utilise:
logger = logging.getLogger(__name__)

# TÂCHE DE FOND (TIMER)
# tourne en boucle toutes les minutes
async def background_game_cleaner():
    while True:
        await asyncio.sleep(60) # Pause de 60 secondes
        try:
            with Session(engine) as session:
                cleanup_inactive_games(session)
        except Exception as e:
            logger.error(f"Erreur lors du nettoyage des parties abandonnées : {e}")



@asynccontextmanager
async def lifespan(app: FastAPI):
    # DÉMARRAGE
    logger.info("Démarrage de l'API Dartsify...")
    create_db_and_tables()
    logger.info("Base de données et tables prêtes.")
    create_initial_admin()
    logger.info("L'admin a bien été créé au démarrage.")
    seed_test_data()
    logger.info("Données de test ajoutées à la base de données.")
    seed_random_games_and_throws()
    logger.info("Parties et lancers de test générés pour les stats des joueurs aléatoirement.")
    
    # Lancement du timer en arrière-plan
    cleaner_task = asyncio.create_task(background_game_cleaner())
    logger.info("Tâche de fond 'Nettoyage des parties inactives' démarrée.")
    
    yield 
    
    # EXTINCTION (Ctrl+C)
    logger.info("Extinction de l'API... Arrêt du timer.")
    cleaner_task.cancel() # tue la boucle proprement
    try:
        await cleaner_task
    except asyncio.CancelledError:
        pass
    logger.info("Tâche de fond arrêtée avec succès.")


# Initialisation de l'API avec le lifespan (plus de on_event car deprécié)
app = FastAPI(title="Dartsify API", lifespan=lifespan)


# Autoriser le Front-end à communiquer avec l'API
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",         # Pour si Mathias code sur la même machine
        "http://100.107.205.98:3000"     # via tunnel tailscale mathias
    ], # En prod -> mettre la vraie URL du front (ex: ["https://dartsify.com"])
    allow_credentials=True,
    allow_methods=["*"], # Autorise les GET, POST, PATCH, DELETE
    allow_headers=["*"], # Autorise le header "Authorization" pour le Token
)


#  Transforme les erreurs complexes de Pydantic en un tableau simple et lisible pour le Front-end (debug)
@app.exception_handler(RequestValidationError)
async def custom_validation_exception_handler(request: Request, exc: RequestValidationError):
    
    formatted_errors = [] #tableau demandé par le front
    
    for error in exc.errors():
        # récupère le champ qui pose problème (le dernier élément de 'loc', ex: "password")
        field = str(error["loc"][-1]) if error["loc"] else "unknown"
        
        # récupère la valeur envoyée par l'utilisateur
        value = str(error.get("input", ""))
        
        # nettoie le message (on retire le vilain "Value error, " automatique du au ValueError de player.py)
        message = error["msg"].replace("Value error, ", "")
        
        # ajout l'objet formaté dans notre tableau (pour mathias)
        formatted_errors.append({
            "field": field,
            "value": value,
            "message": message
        })
    
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={"detail": formatted_errors}
    )


app.include_router(players_router)
app.include_router(auth_router)
app.include_router(targets_router)
app.include_router(games_router)
app.include_router(throws_router)


#Test dans env (DartsifyBackend et taper : uvicorn app.main:app --reload) -> pour tunnel : uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
@app.get("/")
def root():
    return {"message": "API is running "}