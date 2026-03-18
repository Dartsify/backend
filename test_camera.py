import requests
from app.config import RASPBERRY_API_KEY

API_URL = "http://127.0.0.1:8000/throws/"

# La même clé que dans .env 
API_KEY = RASPBERRY_API_KEY

payload = {
    "game_id": 1,
    "x_position": 10.0,  #simuler tirs
    "y_position": 40.0
}

# Le Raspberry Pi met son badge VIP (la clé API) dans l'en-tête
headers = {
    "X-API-Key": API_KEY
}

print("Envoi des coordonnées depuis la caméra...")
reponse = requests.post(API_URL, json=payload, headers=headers)

if reponse.status_code == 200:
    data = reponse.json()
    print(f"Succès ! Le serveur a enregistré :")
    print(f"   - Joueur : {data['player_username']}")
    print(f"   - Tour n°{data['tour_number']} | Fléchette n°{data['dart_number']}")
    print(f"   - Score calculé : {data['calculated_score']} (Multiplicateur x{data['multiplier']})")
else:
    print(f"Erreur de l'API : {reponse.text}")