from sqlmodel import SQLModel, Field
from datetime import datetime


class Player(SQLModel, table=True):

    username: str = Field(primary_key=True, index = True) #vu qeu cle primaire, pas le choix d'avoir une valeur (ne peut pas etre none)
    email: str = Field(index=True)
    name: str
    age: int | None = Field(default=None)
    creation_date: datetime = Field(default_factory=datetime.utcnow)#Date crée auto quand utilisateur est ajouté
    
#Field est utilisé pour : -clé primaire
#                         -val par défaut
#                         -index
#                         -contrainte

#Le | signifie que age peut etre un entier ou vide (None)    