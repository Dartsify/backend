from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import OAuth2PasswordRequestForm
from sqlmodel import Session, select

from app.database import get_session
from app.models.player import Player
from app.security.auth import verify_password, create_access_token

router = APIRouter(prefix="/auth", tags=["auth"])


# Route pour login (centralisé dans auth ->permet porte d'entree pour tout le monde a l'avenir)
@router.post("/login")
def login(form_data: OAuth2PasswordRequestForm = Depends(), session: Session = Depends(get_session)):

    # recup joueur avec son username
    player = session.exec(select(Player).where(Player.username == form_data.username)).first()
    
    #Cas 1 : Le pseudo n'existe pas
    if not player:
        raise HTTPException(
            status_code=401,
            detail=[
                {
                    "Field": "username",
                    "Value": form_data.username,
                    "Message": "Ce nom d'utilisateur n'existe pas."
                }
            ]
        )

    # Cas n2 : Le pseudo existe, mais le mot de passe est faux
    if not verify_password(form_data.password, player.hashed_password):
        raise HTTPException(
            status_code=401,
            detail=[
                {
                    "Field": "password",
                    "Value": form_data.password, # (en prod, évite de renvoyer le mdp en clair, mais pour le dev c'est ok)
                    "Message": "Le mot de passe est incorrect."
                }
            ]
        )

    #Si tout OK, on crée le token
    access_token = create_access_token({"sub": player.username})

    return {
        "access_token": access_token,
        "token_type": "bearer"
    }