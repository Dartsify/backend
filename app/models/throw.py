from sqlmodel import SQLModel, Field
from datetime import datetime


class Throw(SQLModel, table=True):
    id: int = Field(default=None, primary_key=True) 
    tour_number: int  # numéro du tour
    dart_number: int  # 1, 2 ou 3
    time_throw: datetime = Field(default_factory=datetime.utcnow)
    x_position: float #position pour retrouver score avec algo de reconnaissance
    y_position: float
    
    #cles etrangeres
    game_id: int = Field(foreign_key="game_participation.game_id")  
    player_username: str = Field(foreign_key="game_participation.player_username") 