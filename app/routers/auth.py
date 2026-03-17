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
    if not player:
        raise HTTPException(status_code=400, detail="Username incorrect")

    # verif mdp
    if not verify_password(form_data.password, player.hashed_password):
        raise HTTPException(status_code=400, detail="Password incorrect")

    # cree tokenT
    access_token = create_access_token({"sub": player.username})

    return {
        "access_token": access_token,
        "token_type": "bearer" #vient du protocol Oauth 2.0
        #Pour faire une requête vers une route protégée, il faut mettre ce token dans l’en-tête HTTP Authorization comme ceci : 
        # "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
    }