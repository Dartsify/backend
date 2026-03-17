from typing import List
from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select
import logging

from app.database import get_session
from app.models.target import Target, TargetCreate, TargetRead

from app.models.player import Player
from app.security.auth import get_current_user
# seuls les joueurs connectés pourront ajouter des cibles !

router = APIRouter(prefix="/targets", tags=["targets"])
logger = logging.getLogger(__name__)

# Enregistrer une nouvelle cible physique ->il faudra donc un compte admin du site qui enregistre les cibles dans la db pour que si joueur scanne une cible
# elle existe bien dans la db et donc la partie peut se deroule !!!
@router.post("/", response_model=TargetRead)
def create_target(target: TargetCreate,
                  session: Session = Depends(get_session),
                  current_user: Player = Depends(get_current_user)):
    
    logger.info(f"Le joueur {current_user.username} tente d'enregistrer la cible : {target.qr_code}")    
    
    # Vérifier si ce QR Code est déjà enregistré
    existing_target = session.get(Target, target.qr_code)
    if existing_target:
        logger.error("Une cible avec ce QR Code existe déjà sur ce compte")
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
def get_targets(session: Session = Depends(get_session)):
    targets = session.exec(select(Target)).all()
    return targets

# Voir les détails d'une cible via son QR Code (ex: quand on la scanne)
@router.get("/{qr_code}", response_model=TargetRead)
def read_target(qr_code: str, session: Session = Depends(get_session)):
    target = session.get(Target, qr_code)
    if not target:
        raise HTTPException(status_code=404, detail="Cible introuvable.")
    return target