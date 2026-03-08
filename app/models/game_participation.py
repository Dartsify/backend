from sqlmodel import SQLModel, Field, Relationship
from typing import Optional


class GameParticipation(SQLModel, table=True):
    #id: Optional[int] = Field(default=None, primary_key=True)
    game_id: int = Field(foreign_key="game.id",primary_key=True) # on va donc prendre comme cle prim la composition des deux cle etrangeres (impossible d'inserer deux fois le meme joueur pour meme partie)
    player_username: str = Field(foreign_key="player.username", primary_key=True)
    final_score: Optional[int] = None
    position: Optional[int] = None #position du joueur au classement (optionnel a mon avis)



    # Relations ORM (facultative mais pourrait servir pour naviguer)
    # player: Optional["Player"] = Relationship()
    # game: Optional["Game"] = Relationship()