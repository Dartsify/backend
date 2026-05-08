from sqlmodel import SQLModel, Field, Relationship
from datetime import datetime, timezone
from typing import Optional, TYPE_CHECKING

from pydantic import BaseModel

if TYPE_CHECKING:
    from app.models.game import Game
    from app.models.player import Player


class Throw(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True) 
    tour_number: int  # numéro du tour
    dart_number: int  # 1, 2 ou 3 (flechette du tour)
    time_throw: datetime = Field(default_factory=datetime.now(timezone.utc))
    
    x_position: float #position pour retrouver score avec algo de reconnaissance
    y_position: float
    
    camera_id: int | None = Field(default=None) #pour savoir quelle cam a idd quel tir(ideal dans nos tests pour voir ou ca plante)
    #Points (score et multiplier) calculés par backend (utils/dartboard_math) en fonction de x et y
    calculated_score: int
    multiplier: int = Field(default=1)
    
    #cles etrangeres
    game_id: int = Field(foreign_key="game.id")  
    player_username: str = Field(foreign_key="player.username") 
    
    game: Optional["Game"] = Relationship(back_populates="throws")
    player: Optional["Player"] = Relationship(back_populates="throws")
    

#Ce que le raspberry pi envoie
class ThrowCreate(SQLModel):
    game_id: int
    x_position: float
    y_position: float
   
    

class ThrowRead(SQLModel):
    id: int
    game_id: int
    player_username: str
    tour_number: int
    dart_number: int
    x_position: float
    y_position: float
    calculated_score: int
    multiplier: int
    time_throw: datetime
    
    

# Ce que le téléphone/pc enverra pour un lancer manuel ou raté
class ManualThrowCreate(BaseModel):
    game_id: int
    points: int =Field(ge=0, le=60, description="Le score d'une fléchette est de max 60 (T20)")
    multiplier: int = Field(ge=1, le= 3, description="Simple (1), Double (2) ou Triple (3)")