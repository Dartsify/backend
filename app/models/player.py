from sqlmodel import SQLModel, Field
from datetime import datetime
from typing import Optional


class Player(SQLModel, table=True):

    username: str = Field(primary_key=True, index = True) #vu qeu cle primaire, pas le choix d'avoir une valeur (ne peut pas etre none)
    email: str 
    name: str
    age: Optional[int] = None
    #mdp hashé
    hashed_password: str
    creation_date: datetime = Field(default_factory=datetime.utcnow)#Date crée auto quand utilisateur est ajouté
    
    
    
    
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