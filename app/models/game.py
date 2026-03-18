from sqlmodel import SQLModel, Field, Relationship
from datetime import datetime
from enum import Enum
from typing import Optional, List, TYPE_CHECKING

if TYPE_CHECKING:
    from app.models.target import Target
    from app.models.game_participation import GameParticipation
    from app.models.throw import Throw

class GameStatus(str, Enum):#version plus propre pour determine le statut de la partie
    in_progress = "in_progress"
    finished = "finished"
    

class Game(SQLModel, table=True):
    
    id: Optional[int] = Field(default=None, primary_key=True)#En mettant id: Optional[int] = Field(default=None, primary_key=True), tu dis à Python : "Laisse-le vide pour l'instant, c'est la base de données qui s'en occupera quand ce sera le moment de le sauvegarder."
    mode: str = Field(index=True) #mode obligatoire pour jouer
    start_date: datetime = Field(default_factory=datetime.utcnow)
    status: GameStatus = Field(default=GameStatus.in_progress) #par defaut on dira que la partie est en train d'etre jouee
    
    #cle etrangere vers cible
    target_qr_code: str = Field(foreign_key="target.qr_code") #cle etrangere venant de la table target
    
    #gestion des tours (en live)
    current_player_username: Optional[str] = None
    current_turn_number: int = Field(default=1)
    current_dart_number: int = Field(default=1)
    
    # relation optionnelle pour SQLAlchemy / ORM
    target: Optional["Target"] = Relationship(back_populates="games")
    participations: List["GameParticipation"] = Relationship(back_populates="game")
    throws: List["Throw"] = Relationship(back_populates="game")
    
    
#definition de nos modes de jeux
class GameModeAllowed(str, Enum):
    mode_501 = "501"
    mode_301 = "301"
    mode_perso = "perso"


# ce que tel du joueur envoie quand il scanne la cible et choisit le mode
class GameCreate(SQLModel):
    target_qr_code: str
    mode: GameModeAllowed = GameModeAllowed.mode_501 #pour dire que par défaut on lance un 501
    
#ce que APi renvoie quand partie créé
class GameRead(SQLModel):
    id: int
    mode: str
    start_date: datetime
    status: GameStatus
    target_qr_code: str
    

    