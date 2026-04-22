import requests
from app.config import RASPBERRY_API_KEY

API_URL = "http://127.0.0.1:8000/throws/"

# La même clé que dans .env 
API_KEY = RASPBERRY_API_KEY

payload = {
    "target_id": "000001",  
    "x_position": 250.0,  #simuler tirs
    "y_position": 200.0,
    "camera_id" : 1 #simuler la camera 1
}

# Le Raspberry Pi met son badge VIP (la clé API) dans l'en-tête
headers = {
    "X-API-Key": API_KEY
}

print("Envoi des coordonnées depuis la caméra...")
reponse = requests.post(API_URL, json=payload, headers=headers)
# try :
if reponse.status_code == 200:
    data = reponse.json()
    print(f"Succès ! Le serveur a enregistré :")
    print(f"   - Joueur : {data['player_username']}")
    print(f"   - Tour n°{data['tour_number']} | Fléchette n°{data['dart_number']}")
    print(f"   - Score calculé : {data['calculated_score']} (Multiplicateur x{data['multiplier']})")
else:
    print(f"Erreur de l'API : {reponse.text}")
        
# except requests.exceptions.ConnectionError:
#     print("  Erreur : Impossible de contacter le serveur. Vérifie que :")
#     print("   1. Tailscale est connecté sur les deux machines.")
#     print("   2. Tu as lancé Uvicorn avec --host 0.0.0.0")
#     print("   3. Ton pare-feu Windows autorise le port 8000.")