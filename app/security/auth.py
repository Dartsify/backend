import bcrypt
from datetime import datetime, timedelta
from jose import JWTError, jwt

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlmodel import Session

from app.config import SECRET_KEY, ACCESS_TOKEN_EXPIRE_MINUTES, ALGORITHM
from app.database import get_session
from app.models.player import Player

# indique à FastAPI où les joueurs doivent aller pour s'authentifier
# (dans routers/auth.py)
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/login")



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

#fonction pour securite
def get_current_user(token: str = Depends(oauth2_scheme), session: Session = Depends(get_session)):
    #si quelque chose cloche avec le token
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Impossible de valider les identifiants (Token invalide ou expiré)",
        headers={"WWW-Authenticate": "Bearer"},
    )
    
    try:
        # essai de décoder le token avec notre clé secrète
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        
        # recupère le "sub" (le username qu'on avait mis lors du login)
        username: str = payload.get("sub")
        if username is None:
            raise credentials_exception
            
    except JWTError:
        # Si le token est expiré ou qu'il a été falsifié-> erreur
        raise credentials_exception

    # Si le token est bon, chercher joueur correspondant dans db
    player = session.get(Player, username)
    if player is None:
        raise credentials_exception
  
    return player