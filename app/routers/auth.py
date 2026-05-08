from fastapi import APIRouter, Depends, HTTPException, Response 
from fastapi.security import OAuth2PasswordRequestForm
from sqlmodel import Session, select

from app.database import get_session
from app.models.player import Player
from app.security.auth import verify_password, create_access_token

router = APIRouter(prefix="/auth", tags=["auth"])


# Route pour login (centralisé dans auth ->permet porte d'entree pour tout le monde a l'avenir)
@router.post("/login")
def login(response: Response, 
        form_data: OAuth2PasswordRequestForm = Depends(),
        session: Session = Depends(get_session)):

    # recup joueur avec son username
    player = session.exec(select(Player).where(Player.username == form_data.username)).first()
    
    #Cas 1 : Le pseudo n'existe pas
    if not player:
        raise HTTPException(
            status_code=401,
            detail=[
                {
                    "field": "username",
                    "value": form_data.username,
                    "message": "Ce nom d'utilisateur n'existe pas."
                }
            ]
        )

    # Cas 2 : Le pseudo existe, mais le mot de passe est faux
    if not verify_password(form_data.password, player.hashed_password):
        raise HTTPException(
            status_code=401,
            detail=[
                {
                    "field": "password",
                    "value": form_data.password,
                    "message": "Le mot de passe est incorrect."
                }
            ]
        )

    #Si tout OK : crée le token
    access_token = create_access_token({"sub": player.username})

    # pour enregitrer le token dans un cookie sécurisé (pour que le client puisse l'envoyer automatiquement à chaque requête)
    response.set_cookie(
        key="access_token",
        value=f"Bearer {access_token}",
        httponly=True,  # Protège contre les failles XSS (JavaScript ne peut pas le voler)
        samesite="lax", # Autorise l'envoi du cookie pour les requêtes sur le même réseau
        secure=False,   # IMPORTANT : Reste sur False tant que en HTTP (sans SSL/HTTPS) -> a changer a l'avenir en true pour prod
        max_age=86400   # Le cookie expirera dans 24h (86400 secondes)
    )

    return {
        "access_token": access_token,
        "token_type": "bearer"
    }