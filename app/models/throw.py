from sqlmodel import SQLModel, Field, Relationship
from datetime import datetime
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from app.models.game import Game
    from app.models.player import Player


class Throw(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True) 
    tour_number: int  # numéro du tour
    dart_number: int  # 1, 2 ou 3 (flechette du tour)
    time_throw: datetime = Field(default_factory=datetime.utcnow)
    
    x_position: float #position pour retrouver score avec algo de reconnaissance
    y_position: float
    
    #Points calculés par backend en fonction de x et y
    calculated_score: Optional[int] = Field(default=None)
    
    #cles etrangeres
    game_id: int = Field(foreign_key="game.id")  
    player_username: str = Field(foreign_key="player.username") 
    
    #relations
    game: Optional["Game"] = Relationship(back_populates="throws")
    player: Optional["Player"] = Relationship(back_populates="throws")