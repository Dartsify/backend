from fastapi import FastAPI
from app.database import create_db_and_tables

from app.routers import players, games, targets, throws, participations

# Create database tables on startup (when the app starts)
app = FastAPI()


@app.on_event("startup")
def on_startup():
    create_db_and_tables()


# app.include_router(players.router)
# app.include_router(games.router)
# app.include_router(targets.router)
# app.include_router(throws.router)
# app.include_router(participations.router)

#Test 
@app.get("/")
def root():
    return {"message": "API is running"}