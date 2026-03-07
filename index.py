from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Query
from sqlmodel import Field, Session, SQLModel, create_engine, select

class Hero(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(index=True)
    age: int | None = Field(default=None, index=True)
    secret_name: str

# Creat an engine(what holds the connection with db) -> one single engine object for the entire app
sqlite_file_name = "database.db"
sqlite_url = f"sqlite:///{sqlite_file_name}"

connect_args = {"check_same_thread": False} # allows FastAPI to use the same SQLite database in diff threads (necessary)
engine = create_engine(sqlite_url, connect_args=connect_args)

# Create the tables
def create_db_and_tables():
    SQLModel.metadata.create_all(engine) # create the tables for all the table models

# Create Session dependency -> session is what stores the objects in memory and keeps track of any changes (then uses the engine to communicate with the database and save the changes)
def get_session():
    with Session(engine) as session:
        yield session # new session for each request (single session per request)


SessionDep = Annotated[Session, Depends(get_session)] # we will use this Annotated Dependency to simplify the rest of the code (that will use this dep.)

# Create database tables on startup (when the app starts)
app = FastAPI()

@app.on_event("startup")
def on_startup():
    create_db_and_tables()

# Create a Hero
@app.post("/heroes")
def create_hero(hero: Hero, session: SessionDep) -> Hero: # on ajoute une nouvel hero
    session.add(hero) # add the hero to the session
    session.commit() # commit the changes to the database
    session.refresh(hero) # refresh the hero object with the new data from the database (like the id)
    return hero # return the hero object (with the new id)

# Read Heroes
@app.get("/heroes/")
def read_heroes(
    session: SessionDep,
    offset: int = 0,
    limit: Annotated[int, Query(le=100)] = 100,
) -> list[Hero]:
    heroes = session.exec(select(Hero).offset(offset).limit(limit)).all()
    return heroes

# Read one Hero by id
@app.get("/heroes/{hero_id}")
def read_hero(hero_id: int, session: SessionDep) -> Hero:
    hero = session.get(Hero, hero_id)
    if not hero:
        raise HTTPException(status_code=404, detail="Hero not found")
    return hero

# Delete a Hero by id
@app.delete("/heroes/{hero_id}")
def delete_hero(hero_id: int, session: SessionDep):
    hero = session.get(Hero, hero_id)
    if not hero:
        raise HTTPException(status_code=404, detail="Hero not found")
    session.delete(hero)
    session.commit()
    return {"ok": True}