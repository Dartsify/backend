from sqlmodel import SQLModel, Field, Relationship
from datetime import datetime
from enum import Enum
from typing import Optional


class GameStatus(str, Enum):#version plus propre pour determine le statut de la partie
    in_progress = "in_progress"
    finished = "finished"
    

class Game(SQLModel, table=True):
    
    id: int | None = Field(default=None, primary_key=True)#Ici on ne fourni pas l'id de la partie mais c'est bien la db qui le genere automatiquement (different du username de player)
    mode: str = Field(index=True) #mode obligatoire pour jouer
    start_date: datetime = Field(default_factory=datetime.utcnow)
    status: GameStatus = Field(default=GameStatus.in_progress) #par defaut on dira que la partie est en train d'etre jouee
    
    target_qr_code: int = Field(foreign_key="target.qr_code") #cle etrangere venant de la table target
    
    
    # relation optionnelle pour SQLAlchemy / ORM
    # target: Optional["Target"] = Relationship(back_populates="games")
    
    