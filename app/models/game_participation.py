from sqlmodel import SQLModel, Field, Relationship
from typing import Optional, List, TYPE_CHECKING

if TYPE_CHECKING:
    from app.models.game import Game
    from app.models.player import Player
    from app.models.throw import Throw

class GameParticipation(SQLModel, table=True):
    #id: Optional[int] = Field(default=None, primary_key=True)
    game_id: int = Field(foreign_key="game.id",primary_key=True) # on va donc prendre comme cle prim la composition des deux cle etrangeres (impossible d'inserer deux fois le meme joueur pour meme partie)
    player_username: str = Field(foreign_key="player.username", primary_key=True)
    
    current_score: int = Field(default=0) #permet d'avoir le score en direct du joueur
    
    final_score: Optional[int] = None
    position: Optional[int] = None #position du joueur au classement (optionnel a mon avis)



    # Relations ORM (facultative mais pourrait servir pour naviguer)
    player: Optional["Player"] = Relationship(back_populates="participations")
    game: Optional["Game"] = Relationship(back_populates="participations")
    
    
#Renvoyer pour chaque joueur de la partie
class GameParticipationRead(SQLModel):
    player_username: str
    current_score: int
    position: Optional[int] = None
    

from app.models.game import GameRead
# Le modèle complet de la partie AVEC ses joueurs
class GameReadWithParticipants(GameRead):
    # Il hérite de GameRead (donc il a déjà id, mode, status, target_qr_code)
    # Et on lui ajoute la liste des participants 
    participations: List[GameParticipationRead] = []