from typing import List
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session, select
import logging

from app.database import get_session
from app.models.target import TargetUpdate, Target, TargetCreate, TargetRead

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


# Enregistrer une nouvelle cible physique -> protege (admin only): il faut recenser les cibles utilisables dans la db
@router.post("/", response_model=TargetRead)
def create_target(target: TargetCreate,
                  session: Session = Depends(get_session),
                  current_user: Player = Depends(get_current_user)):
    
    logger.info(f"Le joueur {current_user.username} tente d'enregistrer la cible : {target.qr_code}")    
    
    verify_admin(current_user)#check
    
    # Vérifier si ce QR Code est déjà enregistré
    existing_target = session.get(Target, target.qr_code)
    if existing_target:
        logger.error("Une cible avec ce QR Code existe déjà !")
        raise HTTPException(status_code=400, detail="Une cible avec ce QR Code existe déjà sur ce compte.")
        
    db_target = Target(
        qr_code=target.qr_code,
        name=target.name,
        location=target.location
    )
    
    session.add(db_target)
    session.commit()
    session.refresh(db_target)
    
    logger.info(f"Cible {target.qr_code} enregistrée avec succès.")
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
@router.get("/{qr_code}", response_model=TargetRead)
def read_target(qr_code: str,
                session: Session = Depends(get_session),
                current_user: Player = Depends(get_current_user)):
    verify_admin(current_user)
    
    target = session.get(Target, qr_code)
    if not target:
        raise HTTPException(status_code=404, detail="Cible introuvable.")
    return target


# odifier une cible
@router.patch("/{qr_code}", response_model=TargetRead)
def update_target(
    qr_code: str,
    target_update: TargetUpdate,
    session: Session = Depends(get_session),
    current_user: Player = Depends(get_current_user)):
    
    verify_admin(current_user)
    
    db_target = session.get(Target, qr_code)
    if not db_target:
        raise HTTPException(status_code=404, detail="Cible introuvable.")
        
    update_data = target_update.model_dump(exclude_unset=True)
    db_target.sqlmodel_update(update_data)
    
    session.add(db_target)
    session.commit()
    session.refresh(db_target)
    logger.info(f"Cible {qr_code} modifiée par l'admin {current_user.username}.")
    return db_target


# supp une cible
@router.delete("/{qr_code}")
def delete_target(
    qr_code: str,
    session: Session = Depends(get_session),
    current_user: Player = Depends(get_current_user)):
    
    verify_admin(current_user)
    
    db_target = session.get(Target, qr_code)
    if not db_target:
        raise HTTPException(status_code=404, detail="Cible introuvable.")
        
    session.delete(db_target)
    session.commit()
    logger.info(f"Cible {qr_code} supprimée par l'admin {current_user.username}.")
    return {"ok": True, "message": f"Cible {qr_code} supprimée avec succes."}