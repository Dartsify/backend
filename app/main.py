from fastapi import FastAPI
from app.database import create_db_and_tables, create_initial_admin
from app.routers.players import router as players_router
from app.routers.auth import router as auth_router
from app.routers.targets import router as targets_router
from app.routers.games import router as games_router
from app.routers.throws import router as throws_router
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError
from fastapi import Request, status
from fastapi.responses import JSONResponse

import logging
import app.models
# Create database tables on startup (when the app starts)
app = FastAPI(title="Dartsify API")

# Autoriser le Front-end à communiquer avec l'API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # En prod -> mettre la vraie URL du front (ex: ["https://dartsify.com"])
    allow_credentials=True,
    allow_methods=["*"], # Autorise les GET, POST, PATCH, DELETE
    allow_headers=["*"], # Autorise le header "Authorization" pour le Token
)

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


#    Transforme les erreurs complexes de Pydantic en un tableau simple et lisible pour le Front-end.
@app.exception_handler(RequestValidationError)
async def custom_validation_exception_handler(request: Request, exc: RequestValidationError):
    
    formatted_errors = [] #tableau demandé par le front
    
    for error in exc.errors():
        # récupère le champ qui pose problème (le dernier élément de 'loc', ex: "password")
        field = str(error["loc"][-1]) if error["loc"] else "unknown"
        
        # On récupère la valeur envoyée par l'utilisateur
        value = str(error.get("input", ""))
        
        # On nettoie le message (on retire le vilain "Value error, " automatique du au ValueError de player.py)
        message = error["msg"].replace("Value error, ", "")
        
        # On ajoute l'objet formaté dans notre tableau (pour mathias)
        formatted_errors.append({
            "field": field,
            "value": value,
            "message": message
        })
        
    # On renvoie la réponse au format exact demandé par le Front
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={"detail": formatted_errors}
    )



app.include_router(players_router) #mettre le /docs a la fin de l'url
app.include_router(auth_router)
app.include_router(targets_router)
app.include_router(games_router)
app.include_router(throws_router)

#Test dans env (DartsifyBackend et taper : uvicorn app.main:app --reload) -> pour tunnel : uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
@app.get("/")
def root():
    return {"message": "API is running "}
