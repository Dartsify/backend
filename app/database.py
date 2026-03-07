from sqlmodel import SQLModel, create_engine, Session
from fastapi import Depends
from typing import Annotated

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