from sqlmodel import SQLModel, Field, Relationship
from datetime import datetime, timezone
from enum import Enum
from typing import Optional, List, TYPE_CHECKING

if TYPE_CHECKING:
    from app.models.target import Target
    from app.models.game_participation import GameParticipation
    from app.models.throw import Throw

class GameStatus(str, Enum):#version plus propre pour determine le statut de la partie
    in_progress = "in_progress"
    finished = "finished"
    waiting = "waiting" #en attente de joueurs, pas encore commencée (salle d'attente, lobby)
    

class Game(SQLModel, table=True):
    
    id: Optional[int] = Field(default=None, primary_key=True)#En mettant id: Optional[int] = Field(default=None, primary_key=True), ca dit à Python : "Laisse-le vide pour l'instant, c'est la base de données qui s'en occupera quand ce sera le moment de le sauvegarder."
    mode: str = Field(index=True) #mode obligatoire pour jouer 
    
    #quand lobby ouvert (automatique a la creation)
    creation_date: datetime = Field(default_factory= lambda : datetime.now(timezone.utc)) 
    
    #quand partie est lancee(/start)
    start_date: Optional[datetime] = None
    
    #quand partie est terminee (automatique a la fin, si hote quitte ou si victoire)
    end_date: Optional[datetime] = None
    
    status: GameStatus = Field(default=GameStatus.in_progress) #par defaut on dira que la partie est en train d'etre jouee
    
    #cle etrangere vers cible
    target_id: str = Field(foreign_key="target.id") #cle etrangere venant de la table target
    
    #gestion des tours (en live)
    current_player_username: Optional[str] = None
    current_turn_number: int = Field(default=1)
    current_dart_number: int = Field(default=1)
    
    #chrono d'inactivite
    last_interaction: datetime = Field(default_factory= lambda : datetime.now(timezone.utc))
    
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
    target_id: str
    mode: GameModeAllowed = GameModeAllowed.mode_501 #pour dire que par défaut on lance un 501
    
#ce que APi renvoie quand partie créé
class GameRead(SQLModel):
    id: int
    mode: str
    
    creation_date: datetime
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    
    status: GameStatus
    target_id: str
    

class GameListResponse(GameRead):#pour la liste des parties, on ajoute des infos sur la cible et le nombre de joueurs
    target_name: Optional[str] = None
    target_location: Optional[str] = None
    player_count: int = 0
    winner_username: Optional[str] = None
    winner_name: Optional[str] = None