from sqlmodel import SQLModel, Field, Relationship
from datetime import datetime
from typing import List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from app.models.game import Game

class Target(SQLModel, table=True):
    
    qr_code: str = Field(primary_key=True)
    name : str 
    loacation: str
    creation_date: datetime = Field(default_factory=datetime.utcnow)
    
    
    # Pour que SQLModel sache que plusieurs parties peuvent pointer sur la même cible :
    games : list["Game"]= Relationship(back_populates="target")
    
#Modele pour creer nouvelle cible
class TargetCreate(SQLModel):
    qr_code: str
    name: str
    location: str
    
#Modele pour renvoyer infos de cible
class TargetRead(SQLModel):
    qr_code: str
    name: str
    location: str
    creation_date: datetime


