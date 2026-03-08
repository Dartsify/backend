from fastapi import FastAPI
from app.database import create_db_and_tables

from app.routers import players, games, targets, throws, participations

# Create database tables on startup (when the app starts)
app = FastAPI()


@app.on_event("startup")
def on_startup():
    create_db_and_tables()
    
    
#Test des tables
from app.routers.players import router as players_router

app.include_router(players_router) #mettre le /docs a la fin de l'url


#Test dans env (fastapi-test et taper : uvicorn app.main:app --reload)
@app.get("/")
def root():
    return {"message": "API is running "}

