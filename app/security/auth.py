import bcrypt
from datetime import datetime, timedelta
from jose import JWTError, jwt
from app.config import SECRET_KEY, ACCESS_TOKEN_EXPIRE_MINUTES, ALGORITHM



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