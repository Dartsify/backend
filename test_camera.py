import requests
from app.config import RASPBERRY_API_KEY

API_URL = "http://127.0.0.1:8000/throws/"

# La même clé que dans .env 
API_KEY = RASPBERRY_API_KEY

payload = {
    "game_id": 1,
    "player_username": "adri123",
    "tour_number": 1,
    "dart_number": 1,
    "x_position": 2.5,
    "y_position": -1.2,
    "calculated_score": 60
}

# Le Raspberry Pi met son badge VIP (la clé API) dans l'en-tête
headers = {
    "X-API-Key": API_KEY
}

# Envoi du lancer a notre backend
reponse = requests.post(API_URL, json=payload, headers=headers)
print(reponse.json())