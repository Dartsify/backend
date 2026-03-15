from typing import Annotated, List
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session, select
from datetime import datetime

from app.database import SessionDep, get_session 
from app.models.player import Player,PlayerCreate, PlayerRead, PlayerUpdate

from app.security.auth import hash_password 

router = APIRouter(prefix="/players", tags=["players"])


#Creer un joueur
@router.post("/", response_model=PlayerRead)
def create_player(player: PlayerCreate, session: Session = Depends(get_session)):
    
    hashed_pw = hash_password(player.password)
    
    db_player = Player (
        username=player.username,
        email=player.email,
        name=player.name,
        age=player.age,
        creation_date=datetime.utcnow(),
        hashed_password=hashed_pw
    )
    session.add(db_player)
    try:
        session.commit()
    except Exception as e:
        session.rollback()
        raise HTTPException(status_code=400, detail=str(e))
    session.refresh(db_player)
    return db_player



#Lire tous les joueurs (avec offset)
@router.get("/", response_model=List[PlayerRead])
def get_players(
    offset: int = Query(0, ge=0, description="Décalage pour pagination"),
    limit: int = Query(100, le=100, description="Nombre max de joueurs à retourner"),
    session: Session = Depends(get_session)
):
    players = session.exec(select(Player).offset(offset).limit(limit)).all()
    return players



# #Lire un player basé sur son username:
@router.get("/{username}", response_model=PlayerRead)
def read_player(username: str, session: Session = Depends(get_session)):
    player = session.get(Player, username)
    if not player:
        raise HTTPException(status_code=404, detail=f"Player {username} not found")
    return player


# #Modifier un joueur (update)
@router.patch("/{username}", response_model=PlayerRead)
def update_player(username: str, player_update: PlayerUpdate, session: Session = Depends(get_session)):
    player = session.get(Player, username) #recup joueur existant
    if not player:
        raise HTTPException(status_code=404, detail=f"Player {username} not found")

    update_data = player_update.model_dump(exclude_unset=True)
    player.sqlmodel_update(update_data) #appliquer mises a jour

    session.add(player)
    session.commit()
    session.refresh(player)
    return player #Attention de bien renvoye ce qu'on veut dans le Json, si on ne veut pas changer email, on supprime la ligne email


# #Supprimer un joueur(delete)
@router.delete("/{username}")
def delete_player(username: str, session: Session = Depends(get_session)):
    player = session.get(Player, username)
    if not player:
        raise HTTPException(status_code=404, detail=f"Player {username} not found")
    session.delete(player)
    session.commit()
    return {"ok": True}