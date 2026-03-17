from sqlmodel import SQLModel, Field, Relationship
from datetime import datetime
from typing import Optional, List, TYPE_CHECKING

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
    email: str 
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
    email: str
    name: str
    age: int | None = None
    password: str
    
# modèle pour renvoyer au client (profil perso)
class PlayerRead(SQLModel):
    username: str
    email: str
    name: str
    age: Optional[int]
    creation_date: datetime

# modèle pour mise à jour (tout optionnel)
class PlayerUpdate(SQLModel):
    email: Optional[str] = None
    name: Optional[str] = None
    age: Optional[int] = None
    
#modele public(pour un classement par ex)
class PlayerPublic(SQLModel):
    username: str
    name: str
    age: Optional[int]
    creation_date: datetime