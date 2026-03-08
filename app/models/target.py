from sqlmodel import SQLModel, Field, Relationship
from datetime import datetime


class Target(SQLModel, table=True):
    
    qr_code: str = Field(primary_key=True)
    name : str 
    loacation: str
    creation_date: datetime = Field(default_factory=datetime.utcnow)
    
    
    #pas sur de ca mais :
    #Pour que SQLModel sache que plusieurs parties peuvent pointer sur la même cible :
    # games : list["Game"]= Relationship(back_populates="target")