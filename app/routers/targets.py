from typing import List
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session, select
import logging
from datetime import datetime, timedelta

from app.database import get_session
from app.models.target import TargetUpdate, Target, TargetCreate, TargetRead, TargetStatusRead
from app.models.game import Game, GameStatus

from app.models.player import Player
from app.security.auth import get_current_user
# seuls les joueurs connectés pourront ajouter des cibles !

router = APIRouter(prefix="/targets", tags=["targets"])
logger = logging.getLogger(__name__)


#Verif si c'est bien l'admin
def verify_admin(current_user: Player):
    if not current_user.is_admin:
        logger.warning(f"Alerte : Le joueur {current_user.username} a tenté d'accéder à une route Admin.")
        raise HTTPException(
            status_code=403, 
            detail="Accès refusé. Réservé aux administrateurs."
        )


import random
# Enregistrer une nouvelle cible physique -> protege (admin only): il faut recenser les cibles utilisables dans la db
@router.post("/", response_model=TargetRead)
def create_target(target: TargetCreate,
                  session: Session = Depends(get_session),
                  current_user: Player = Depends(get_current_user)):
    
    logger.info(f"Le joueur {current_user.username} tente d'enregistrer une nouvelle cible.")    
    
    verify_admin(current_user) #check
    
    # Génération d'un ID unique à 6 chiffres
    while True:
        # Génère un code entre "000000" et "999999" (zfill rajoute les zéros devant si c'est 42 par ex -> "000042")
        new_id = str(random.randint(0, 999999)).zfill(6)
        
        # vérifie si ce code existe déjà dans la base de données
        existing_target = session.get(Target, new_id)
        if not existing_target:
            break # Le code est unique, on sort de la boucle 
            
    # crée la cible avec l'ID généré automatiquement
    db_target = Target(
        id=new_id,
        name=target.name,
        location=target.location
    )
    
    session.add(db_target)
    session.commit()
    session.refresh(db_target)
    
    logger.info(f"Cible {new_id} enregistrée avec succès par {current_user.username}.")
    return db_target



# Lister toutes les cibles disponibles (enrgistrées dans la db)
@router.get("/", response_model=List[TargetRead])
def get_targets(offset: int = Query(0, ge=0, description="Décalage pour pagination"), #avec pagination 
    limit: int = Query(100, le=100, description="Nombre max de joueurs à retourner"),
    session: Session = Depends(get_session),
    current_user: Player= Depends(get_current_user)):
    
    verify_admin(current_user)
    
    targets = session.exec(select(Target).offset(offset).limit(limit)).all()
    return targets


# Voir les détails d'une cible spécifique via son QR Code 
@router.get("/{target_id}", response_model=TargetStatusRead) #si bug, remettre target_id
def get_target_status(target_id: str, session: Session = Depends(get_session)):
    
    # cherche la cible (Route publique)
    target = session.get(Target, target_id)
    if not target:
        raise HTTPException(status_code=404, detail="Cible introuvable.")

    # on cherche SEULEMENT les parties actives
    active_game = session.exec(
        select(Game)
        .where(Game.target_id == target_id)
        .where(Game.status.in_([GameStatus.waiting, GameStatus.in_progress]))).first() 

    #controle d'inactivite 
    if active_game:
        # On calcule le temps écoulé depuis la dernière interaction
        time_elapsed = datetime.utcnow() - active_game.last_interaction
        
        # Si ça fait plus de 20 minutes (1200 secondes)
        if time_elapsed > timedelta(minutes=20):
            logger.info(f"La partie {active_game.id} a expiré (inactivité). Clôture automatique.")
            active_game.status = GameStatus.finished # On force la fin de la partie
            session.add(active_game)
            session.commit()
            
            # Comme on vient de la fermer, on supprime active_game pour que la suite
            # du code considère la cible comme LIBRE !
            active_game = None
    
    
    # prépare la réponse pour le Front
    if active_game:
        # Scénario A : La cible est OCCUPÉE (salle d'attente ou en train de jouer)
        return TargetStatusRead( 
            id=target.id,
            name=target.name,
            location=target.location,
            creation_date=target.creation_date, 
            #is_occupied=True, #pas specialement utile car on sait le deduire de la game_status
            current_game_id=active_game.id,
            current_game_status=active_game.status # Le front lira "waiting" ou "in_progress"
        )
    else:
        # Scénario B : La cible est LIBRE (aucune partie, ou la dernière est "finished")
        return TargetStatusRead(
            id=target.id,
            name=target.name,
            location=target.location,
            creation_date=target.creation_date, 
            #is_occupied=False,
            current_game_id=None,
            current_game_status=GameStatus.finished # On peut aussi laisser vide (none) ou mettre "finished" pour indiquer que la cible est dispo
        )
        

# modifier une cible
@router.patch("/{id}", response_model=TargetRead)
def update_target(
    id: str,
    target_update: TargetUpdate,
    session: Session = Depends(get_session),
    current_user: Player = Depends(get_current_user)):
    
    verify_admin(current_user)
    
    db_target = session.get(Target, id)
    if not db_target:
        raise HTTPException(status_code=404, detail="Cible introuvable.")
        
    update_data = target_update.model_dump(exclude_unset=True)
    db_target.sqlmodel_update(update_data)
    
    session.add(db_target)
    session.commit()
    session.refresh(db_target)
    logger.info(f"Cible {id} modifiée par l'admin {current_user.username}.")
    return db_target


# supp une cible
@router.delete("/{id}")
def delete_target(
    id: str,
    session: Session = Depends(get_session),
    current_user: Player = Depends(get_current_user)):
    
    verify_admin(current_user)
    
    db_target = session.get(Target, id)
    if not db_target:
        raise HTTPException(status_code=404, detail="Cible introuvable.")
        
    session.delete(db_target)
    session.commit()
    logger.info(f"Cible {id} supprimée par l'admin {current_user.username}.")
    return {"ok": True, "message": f"Cible {id} supprimée avec succes."}