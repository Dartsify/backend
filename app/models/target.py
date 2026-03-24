from sqlmodel import SQLModel, Field, Relationship
from datetime import datetime
from typing import List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from app.models.game import Game

class Target(SQLModel, table=True):
    
    id: str = Field(primary_key=True, min_length=6, max_length=6) #le QR code est la clé primaire, il doit faire exactement 6 caractères pour être valide
    name : str 
    location: str
    creation_date: datetime = Field(default_factory=datetime.utcnow)
    
    
    # Pour que SQLModel sache que plusieurs parties peuvent pointer sur la même cible :
    games : list["Game"]= Relationship(back_populates="target")
    
#Modele pour creer nouvelle cible
class TargetCreate(SQLModel):
    name: str
    location: str #l'admin qui cree une nouvelle cible ne choisi pas son id(l'api le fait tout seul), mais doit lui donner un nom et une localisation pour la différencier des autres cibles
    
#Modele pour renvoyer infos de cible
class TargetRead(SQLModel):
    id: str
    name: str
    location: str
    creation_date: datetime
    
#modele pour modif cible
class TargetUpdate(SQLModel):
    name: Optional[str] = None
    location: Optional[str] = None
    

#Modele qui sert quand on scanne la cible pour voir si elle est libre
class TargetStatusRead(TargetRead):
    # is_occupied: bool
    current_game_id: Optional[int] = None
    current_game_status: Optional[str] = None


