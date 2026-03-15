from dotenv import load_dotenv
import os

load_dotenv()

#Aller recherhcer les diff variables d'env dans le .env (pout mdp secret)
SECRET_KEY = os.getenv("SECRET_KEY") 
ALGORITHM = os.getenv("ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "60"))