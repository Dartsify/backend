import logging
from datetime import datetime, timedelta
from typing import Optional

import bcrypt
from jose import JWTError, jwt

from fastapi import Depends, HTTPException, status, Request 
from fastapi.security import OAuth2PasswordBearer

from sqlmodel import Session
from app.database import get_session

from app.config import SECRET_KEY, ACCESS_TOKEN_EXPIRE_MINUTES, ALGORITHM
from app.models.player import Player

logger = logging.getLogger(__name__)

# indique à FastAPI où les joueurs doivent aller pour s'authentifier
# (dans routers/auth.py)
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/login", auto_error=False) # on met auto_error à False pour pouvoir gérer nous même les cas où le token est absent ou invalide (ex: invité qui rejoint une partie sans être connecté)



def hash_password(password: str) -> str:
    # bcrypt a besoin de bytes, on encode donc la chaîne en utf-8
    pwd_bytes = password[:72].encode('utf-8')
    salt = bcrypt.gensalt()
    hashed_password = bcrypt.hashpw(pwd_bytes, salt)
    # On retourne une string pour la stocker facilement dans la base de données
    return hashed_password.decode('utf-8')




def verify_password(plain_password: str, hashed_password: str) -> bool:
    password_byte_enc = plain_password[:72].encode('utf-8')
    hashed_password_byte_enc = hashed_password.encode('utf-8')
    return bcrypt.checkpw(password_byte_enc, hashed_password_byte_enc)




def create_access_token(data: dict):
    to_encode = data.copy()
    # temps d'exp du token 
    expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt





# Cette fonction cherche le token dans le Header, et sinon dans le Cookie
def get_token_from_header_or_cookie(
    request: Request,
    token_from_header: Optional[str] = Depends(oauth2_scheme)) -> Optional[str]:
    
    if token_from_header:
        return token_from_header
        
    # on fouille dans les Cookies (Méthode SSE / Client-side pour Mathias)
    cookie_token = request.cookies.get("access_token")
    if cookie_token:
        if cookie_token.startswith("Bearer "):
            return cookie_token.split(" ")[1]
        return cookie_token # Au cas où il est sauvegardé sans "Bearer "
        
    return None



#fonction pour securite
def get_current_user(
    token: Optional[str] = Depends(get_token_from_header_or_cookie), # utilise notre extracteur
    session: Session = Depends(get_session)):
    
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Impossible de valider les identifiants (Token invalide ou expiré)",
        headers={"WWW-Authenticate": "Bearer"},
    )
    
    # Si ni le header ni le cookie n'ont de token
    if not token:
        raise credentials_exception
    
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise credentials_exception
            
    except JWTError:
        raise credentials_exception

    player = session.get(Player, username)
    if player is None:
        raise credentials_exception

    return player




# schéma "tolérant" (auto_error=False) : il ne jette pas d'erreur 401 si le token est absent.
oauth2_scheme_optional = OAuth2PasswordBearer(tokenUrl="auth/login", auto_error=False) 

# fonction qui va servir pour les routes où le token est optionnel (ex: rejoindre une partie en tant qu'invité)
def get_current_user_optional(
    token: Optional[str] = Depends(get_token_from_header_or_cookie), # <-- On utilise notre extracteur ici aussi
    session: Session = Depends(get_session)):
    
    # S'il n'y a pas de token envoyé (ni Header, ni Cookie), c'est un invité 
    if not token:
        return None 
        
    try:
        # On réutilise la fonction principale
        return get_current_user(token=token, session=session) 
    except Exception:
        # Si le token est invalide ou expiré -> invité
        return None
    
    
    

#Verif si c'est bien l'admin
def verify_admin(current_user: Player):
    if not current_user.is_admin:
        logger.warning(f"Alerte : Le joueur {current_user.username} a tenté d'accéder à une route Admin.")
        raise HTTPException(
            status_code=403, 
            detail="Accès refusé. Réservé aux administrateurs."
        )
        
    
