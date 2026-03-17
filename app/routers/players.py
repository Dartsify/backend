from typing import Annotated, List
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session, select
from datetime import datetime
import logging

from app.database import SessionDep, get_session 
from app.models.player import Player, PlayerPublic, PlayerCreate, PlayerRead, PlayerUpdate

from app.security.auth import hash_password, get_current_user

router = APIRouter(prefix="/players", tags=["players"]) #creation route
logger = logging.getLogger(__name__) # Récupère le logger configuré

#Creer un joueur
@router.post("/", response_model=PlayerRead)
def create_player(player: PlayerCreate, session: Session = Depends(get_session)):
    
    logger.info(f"Tentative de création du joueur : {player.username}")
    
    # Vérifier si pseudo existe déjà 
    existing_player = session.get(Player, player.username)
    if existing_player:
        logger.error("Le pseudo qui essaie d'être créé est déjà pris ! ")
        raise HTTPException(status_code=400, detail="Ce pseudo est déjà pris.")
    
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
        logger.error(f"Échec de la création du joueur {player.username}. Erreur : {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))
    session.refresh(db_player)
    logger.info(f"Joueur {player.username} créé avec succès.")
    return db_player


#Lire son propre profil ->route protégée
#mettre /me avant {username} pour que FastAPI ne confonde pas les 2routes
@router.get("/me", response_model=PlayerRead)
def read_current_player(current_user: Player=Depends(get_current_user)):
    return current_user#si token valide on a direct le joueur


#Lire tous les joueurs (avec offset) ->publique
@router.get("/", response_model=List[PlayerPublic])
def get_players(
    offset: int = Query(0, ge=0, description="Décalage pour pagination"),
    limit: int = Query(100, le=100, description="Nombre max de joueurs à retourner"),
    session: Session = Depends(get_session)
):
    players = session.exec(select(Player).offset(offset).limit(limit)).all()
    logger.info(f"Liste des joueurs retournée avec succès. ")
    return players



# #Lire un player spécifique basé sur son username ->publique
@router.get("/{username}", response_model=PlayerPublic)
def read_player(username: str, session: Session = Depends(get_session)):
    player = session.get(Player, username)
    if not player:
        raise HTTPException(status_code=404, detail=f"Player {username} not found")
    return player


# #Modifier un joueur (update)-> protégé car ca doit etre son propre profil
@router.patch("/{username}", response_model=PlayerRead)
def update_player(username: str,
                  player_update: PlayerUpdate,
                  session: Session = Depends(get_session),
                  current_user: Player = Depends(get_current_user)):#verif du token
    
    if current_user.username != username : #verif si joueuer connecte est bien celui de l'url
        logger.warning(f"Alerte : {current_user.username} a essayé de modifier le compte de {username}")
        raise HTTPException(status_code=403, detail="Vous n'avez pas l'autorisation de modifier ce compte.")

    player = session.get(Player, username) #recup joueur existant
    if not player:
        raise HTTPException(status_code=404, detail=f"Player {username} not found")

    update_data = player_update.model_dump(exclude_unset=True)
    player.sqlmodel_update(update_data) #appliquer mises a jour

    session.add(player)
    session.commit()
    session.refresh(player)
    logger.info(f"Le joueur {username} a mis à jour son profil.")
    return player #Attention de bien renvoye ce qu'on veut dans le Json, si on ne veut pas changer email, on supprime la ligne email


# #Supprimer un joueur(delete)->protégé (ca doit etre son profil a lui)
@router.delete("/{username}")
def delete_player(username: str,
                  session: Session = Depends(get_session),
                  current_user: Player = Depends(get_current_user)):
    
    if current_user.username != username:
        logger.warning(f"Alerte : {current_user.username} a essayé de supprimer le compte de {username}")
        raise HTTPException(status_code=403, detail="Vous n'avez pas l'autorisation de supprimer ce compte.")
    
    player = session.get(Player, username)
    if not player:
        raise HTTPException(status_code=404, detail=f"Player {username} not found")
    session.delete(player)
    session.commit()
    logger.info(f"Le joueur {username} a supprimé son compte.")
    return {"ok": True}