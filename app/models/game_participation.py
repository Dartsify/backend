from sqlmodel import SQLModel, Field, Relationship
from typing import Optional, List, TYPE_CHECKING
from enum import Enum

if TYPE_CHECKING:
    from app.models.game import Game
    from app.models.player import Player
    from app.models.throw import Throw
    
class ValidationStatus(str, Enum):
    pending = "pending" #stand by, partie a ete jouee et en attente de validation
    validated ="validated" #stats sont comptabilisees pour joueur
    rejected = "rejected" #pas lui donc on compte pas les stats
     

class GameParticipation(SQLModel, table=True):
    #id: Optional[int] = Field(default=None, primary_key=True)
    game_id: int = Field(foreign_key="game.id",primary_key=True) # on va donc prendre comme cle prim la composition des deux cle etrangeres (impossible d'inserer deux fois le meme joueur pour meme partie)
    player_username: str = Field(foreign_key="player.username", primary_key=True)
    
    current_score: int = Field(default=0) #permet d'avoir le score en direct du joueur
    
    final_score: Optional[int] = None
    position: Optional[int] = None #position du joueur au classement (optionnel a mon avis)

    #Par defaut quand on invite qqun, c'est en stand by mais l'hote de la partie sera mis en validated d'office
    status: ValidationStatus = Field(default=ValidationStatus.pending)

    # Relations ORM (facultative mais pourrait servir pour naviguer)
    player: Optional["Player"] = Relationship(back_populates="participations")
    game: Optional["Game"] = Relationship(back_populates="participations")
    
    
#Renvoyer pour chaque joueur de la partie
class GameParticipationRead(SQLModel):
    game_id: int
    player_username: str
    player_name: Optional[str] = None
    current_score: int
    position: Optional[int] = None
    status: ValidationStatus
    
    checkout_suggestion: Optional[List[str]] = []
    

from app.models.game import GameRead
# Le modèle complet de la partie AVEC ses joueurs
class GameReadWithParticipants(GameRead):
    # Il hérite de GameRead (donc il a déjà id, mode, status, target_id)
    # Et on lui ajoute la liste des participants 
    participations: List[GameParticipationRead] = []