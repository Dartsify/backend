from sqlmodel import SQLModel, Field, Relationship
from typing import Optional, List, TYPE_CHECKING, Dict
from enum import Enum
from datetime import datetime, timezone

if TYPE_CHECKING: #pour eviter imports circulaires et pour que VScode comprenne que les classes existent
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

    join_date: datetime = Field(default_factory= lambda :datetime.now(timezone.utc)) # L'heure exacte où il rejoint
    
    # Relations ORM (qui permet de generer une jointure SQL tout seul en arriere plan, pas besoin de faire une requete supp)
    player: Optional["Player"] = Relationship(back_populates="participations")
    game: Optional["Game"] = Relationship(back_populates="participations") #grace au back_pop, ca va dans les 2 sens et pas besoin de requete sql trop complexe
    # indication de type pour le futur, ne pas chercher a effectuer ce mot tout de suite (avec le probleme d'imports circulaires)
    
    
#Renvoyer pour chaque joueur de la partie
class GameParticipationRead(SQLModel):
    # game_id: int
    player_username: str
    player_name: Optional[str] = None
    is_host: bool 
    current_score: int
    position: Optional[int] = None
    status: ValidationStatus
    
    checkout_suggestion: Optional[List[str]] = []
    
    is_friend: bool =False #pour dire si le joueur est ami ou pas avec celui qui regarde (utile pour le front)
    current_average: float = 0.0 #pour afficher la moyenne actuelle du joueur dans la partie 
    
    last_3_points: list[dict] = [] #pour afficher les points des 3 derniers lancers du joueur dans la partie 

from app.models.game import GameRead
# Le modèle complet de la partie AVEC ses joueurs
class GameReadWithParticipants(GameRead):
    # Il hérite de GameRead (donc il a déjà id, mode, status, target_id)
    #on ajoute le nom et lieu de cible pour le front
    target_name: Optional[str] = None
    target_location: Optional[str] = None
    
    current_player_username: str | None = None
    current_turn_number: int
    current_dart_number: int
    
    # Et on lui ajoute la liste des participants 
    participations: List[GameParticipationRead] = []
    
    board_hits: Dict[str, List[Dict[str, float]]] = {"current_player": [], "others": []}