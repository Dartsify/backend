from sqlmodel import SQLModel, Field, Relationship
from pydantic import EmailStr, field_validator
from datetime import datetime
from typing import Optional, List, TYPE_CHECKING
from enum import Enum

if TYPE_CHECKING:
    # On importe les autres tables uniquement "virtuellement" pour éviter l'import circulaire
    from app.models.game_participation import GameParticipation
    from app.models.throw import Throw

# le fichier game.py a besoin d'importer Throw pour dire qu'une partie contient plusieurs lancers.

# le fichier throw.py a besoin d'importer Game pour dire qu'un lancer appartient à une partie.

# Le crash : Python lit game.py, qui lui dit d'aller lire throw.py, qui lui dit de retourner lire game.py... Python tourne en boucle et l'application plante instantanément !

# La solution magique : TYPE_CHECKING
# C'est une variable spéciale de Python qui vaut False quand ton application tourne en vrai, mais qui vaut True pour l'éditeur de code (VS Code) quand il inspecte ton code.
# En mettant les imports dans le bloc if TYPE_CHECKING:, on triche :
# l'éditeur de code lit l'import et peut te faire l'auto-complétion intelligente.
# Quand Uvicorn lance le serveur pour de vrai, Python ignore totalement ces imports (évitant ainsi le crash). SQLModel se débrouillera tout seul en lisant les noms des classes entre guillemets ("Game", "Throw").

class Player(SQLModel, table=True):

    username: str = Field(primary_key=True, index = True) #vu qeu cle primaire, pas le choix d'avoir une valeur (ne peut pas etre none)
    email: Optional[str] = Field(default=None, unique=True)
    name: str
    age: Optional[int] = None
    #mdp hashé
    hashed_password: Optional[str]= Field(default=None)
    creation_date: datetime = Field(default_factory=datetime.utcnow)#Date crée auto quand utilisateur est ajouté
    
    is_admin: bool = Field(default=False)
    
    #le drapeau pour dire que c'est un invite
    is_guest: bool = Field(default=False)
    
    participations: List["GameParticipation"] = Relationship(back_populates="player")
    throws: List["Throw"] = Relationship(back_populates="player") #back_populates : C'est ce qui indique à SQLModel de faire le lien dans les deux sens de manière automatique
    
#Field est utilisé pour : -clé primaire
#                         -val par défaut
#                         -index
#                         -contrainte

#Le | signifie que age peut etre un entier ou vide (None) 
    

class PlayerCreate(SQLModel):
    username: str
    email: EmailStr
    name: str
    #gt = greather than (0)
    age: int = Field(gt=0, description="L'âge doit etre strictement supérieur à 0")
    password: str
    
    #Validateur de mdp (6 caractere et 1majuscule (peut etre changer))
    @field_validator('password')
    @classmethod
    def validate_password(cls, value):
        if len(value) < 6:
            raise ValueError("Le mot de passe doit contenir au moins 6 caractères.")
        if not any(char.isupper() for char in value):
            raise ValueError("Le mot de passe doit contenir au moins une majuscule.")
        return value
    
    
    
# modèle pour renvoyer au client (profil perso)
class PlayerRead(SQLModel):
    username: str
    email: Optional[str] = None
    name: str
    age: Optional[int] = None
    creation_date: datetime
    

# modèle pour mise à jour (tout optionnel)
class PlayerUpdate(SQLModel):
    email: Optional[EmailStr] = None
    name: Optional[str] = None
    age: Optional[int] =  Field(default=None, gt=0)
    
#modele public(pour un classement par ex)
class PlayerPublic(SQLModel):
    username: str
    name: str
    age: Optional[int] = None
    creation_date: datetime


#Modele pour les stats d'un joueur    
from pydantic import BaseModel
class PlayerStats(BaseModel):
    total_games_played: int
    total_wins: int
    win_rate_percentage: float
    average_points_per_dart: float
    total_darts_thrown: int
    
    favorite_target: Optional[int] = None  # La zone la plus touchée (ex: 20)
    total_misses: int = 0                  
    total_triple_20: int = 0      
    total_180s: int = 0
    total_100_plus: int = 0 # Nombre de fois où le joueur a fait 100 points ou plus en un tour (3 fléchettes)         
    cursed_target: Optional[int] = None # La zone la moins visée 
    
#Modele pour changer le mot de passe
class PasswordUpdate(BaseModel):
    old_password: str
    new_password: str
    
    @field_validator('new_password')
    @classmethod
    def validate_new_password(cls, value):
        if len(value) < 6:
            raise ValueError("Le nouveau mot de passe doit contenir au moins 6 caractères.")
        if not any(char.isupper() for char in value):
            raise ValueError("Le nouveau mot de passe doit contenir au moins une majuscule.")
        return value
    
    
    
# Les statuts possibles
class FriendshipStatus(str, Enum):
    pending = "pending"   # Demande envoyée
    accepted = "accepted" 
    rejected = "rejected"  
    
      
#table pour liste d'amis
class Friendship(SQLModel, table=True):
    # Clés primaires composées : l'amitié est unique entre ces deux personnes
    user_username: str = Field(foreign_key="player.username", primary_key=True)
    friend_username: str = Field(foreign_key="player.username", primary_key=True)
    
    status: FriendshipStatus = Field(default=FriendshipStatus.pending)
    
    created_at: datetime = Field(default_factory=datetime.utcnow)
    
    
# Modèle pour l'affichage des demandes d'amis en attente
class FriendRequestResponse(PlayerPublic):
    request_date: datetime
    

#modele pour affichage de la list d'amis avec stats
class FriendResponse(PlayerPublic):
    friends_since: datetime
    games_played_together: int
    games_won_against: int