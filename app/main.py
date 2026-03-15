from fastapi import FastAPI
from app.database import create_db_and_tables
from app.routers.players import router as players_router
from app.routers.auth import router as auth_router
# Create database tables on startup (when the app starts)
app = FastAPI()


@app.on_event("startup")
def on_startup():
    create_db_and_tables()


app.include_router(players_router) #mettre le /docs a la fin de l'url
app.include_router(auth_router)

#Test dans env (fastapi-test et taper : uvicorn app.main:app --reload)
@app.get("/")
def root():
    return {"message": "API is running "}

