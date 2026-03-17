from dotenv import load_dotenv
import os

load_dotenv()

#Aller recherhcer les diff variables d'env dans le .env (pout mdp secret)
SECRET_KEY = os.getenv("SECRET_KEY") 
ALGORITHM = os.getenv("ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "60"))

#Pour admin
ADMIN_USERNAME=os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD=os.getenv("ADMIN_PASSWORD", "admin_password")
ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "admin_dartsify@gmail.com")
ADMIN_NAME=os.getenv("ADMIN_NAME","Admin Dartsify") 