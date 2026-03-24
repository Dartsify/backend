from sqlmodel import SQLModel, Field, Relationship
from pydantic import EmailStr, field_validator
from datetime import datetime
from typing import Optional, List, TYPE_CHECKING
from pydantic_core import PydanticCustomError

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
    email: str = Field(unique=True)
    name: str
    age: Optional[int] = None
    #mdp hashé
    hashed_password: str
    creation_date: datetime = Field(default_factory=datetime.utcnow)#Date crée auto quand utilisateur est ajouté
    
    is_admin: bool = Field(default=False)
    
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
    email: str
    name: str
    age: Optional[int]
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
    age: Optional[int]
    creation_date: datetime


#Modele pour les stats d'un joueur    
from pydantic import BaseModel
class PlayerStats(BaseModel):
    total_games_played: int
    total_wins: int
    win_rate_percentage: float
    average_points_per_dart: float
    total_darts_thrown: int
    
    
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