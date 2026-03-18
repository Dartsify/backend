from fastapi import APIRouter, Depends, HTTPException, Security
from fastapi.security.api_key import APIKeyHeader 
from sqlmodel import Session, select
import logging

from app.database import get_session
from app.models.throw import Throw, ThrowCreate, ThrowRead
from app.models.game import Game, GameStatus
from app.models.game_participation import GameParticipation
from app.models.player import Player

from app.config import RASPBERRY_API_KEY #cle secrete pour lier raspberry

from app.utils.dartboard_math import get_score_and_multiplier

router = APIRouter(prefix="/throws", tags=["throws (Only for Raspberry Pi)"])
logger = logging.getLogger(__name__)

# On dit à FastAPI de chercher un en-tête appelé "X-API-Key" dans la requête
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=True)

#verif si bon raspberry
def verify_raspberry_pi(api_key: str = Security(api_key_header)):
    if api_key != RASPBERRY_API_KEY:
        logger.warning("Une machine non autorisée a tenté d'envoyer un lancer !")
        raise HTTPException(status_code=403, detail="Accès refusé. Matériel non autorisé.")
    return True


#-----------------------------------------------------------------------------------------------
#code a mettre sur raspberry
# import requests

# API_URL = "http://127.0.0.1:8000/throws/"

# # La même clé que dans .env 
# API_KEY = "MaCleSecretePourLePi_Dart123!" 

# payload = {
#     "game_id": 1,
#     "player_username": "adri123",
#     "tour_number": 1,
#     "dart_number": 1,
#     "x_position": 2.5,
#     "y_position": -1.2,
#     "calculated_score": 60
# }

# # Le Raspberry Pi met son badge VIP (la clé API) dans l'en-tête
# headers = {
#     "X-API-Key": API_KEY
# }

# # Envoi du lancer a notre backend
# reponse = requests.post(API_URL, json=payload, headers=headers)
# print(reponse.json())
#-----------------------------------------------------------------------------------------------





#enregistrer un lancer de flechette
@router.post("/", response_model=ThrowRead)
def register_throw(
    throw_in: ThrowCreate,
    session: Session = Depends(get_session),
    is_hardware_authorized: bool = Depends(verify_raspberry_pi)):
    
    # verif que partie existe et qu'elle est bien "en cours"
    game = session.get(Game, throw_in.game_id)
    if not game:
        raise HTTPException(status_code=404, detail="Partie introuvable.")
    if game.status != GameStatus.in_progress:
        raise HTTPException(status_code=400, detail="Cette partie est déjà terminée.")

    #recup la ligne de score du joueur en question
    participation = session.get(GameParticipation, {"game_id": throw_in.game_id, "player_username": throw_in.player_username})
    if not participation:
        raise HTTPException(status_code=404, detail=f"Le joueur {throw_in.player_username} ne participe pas à cette partie.")

    # Le backend calcule lui-même les points avec X et Y (app.utils.dartboard_math)
    points, multiplicateur = get_score_and_multiplier(throw_in.x_position, throw_in.y_position)

    #Application de la logique du jeu (maj du score)
    if game.mode in ["501", "301"]: #On fait un classique avec la regle du double out
        # on soustrait
        nouveau_score = participation.current_score - points
      
        is_bust = False
        
        # Condition 1 et 2 : on passe sous 0, ou on tombe sur 1 (impossible de finir par un double)
        if nouveau_score < 0 or nouveau_score == 1:
            is_bust = True
        # Condition 3 : on tombe sur 0, mais ce n'est pas un double 
        elif nouveau_score == 0 and multiplicateur != 2:
            is_bust = True

        if is_bust:
            logger.info(f"BUST ! Le joueur {throw_in.player_username} a busté ! (Score théorique: {nouveau_score})")
        
            #etape de trouve les points marques pendant ce tour ci pour les annules et revenir aux points du tour d'avant
            previous_throws_this_turn = session.exec(
                select(Throw)
                .where(Throw.game_id == game.id)
                .where(Throw.player_username == throw_in.player_username)
                .where(Throw.tour_number == throw_in.tour_number)
            ).all()
            
            points_a_annuler = sum(t.calculated_score for t in previous_throws_this_turn)
            
            participation.current_score = participation.current_score + points_a_annuler            
            logger.info(f"Le score de {throw_in.player_username} est réinitialisé à {participation.current_score}")
        
        #condition de victoire en double out
        elif nouveau_score == 0 and multiplicateur == 2:
            participation.current_score = 0
            game.status = GameStatus.finished # joueur a gagné
            logger.info(f"VICTOIRE ! {throw_in.player_username} a gagné la partie !")
        
        # lancer normal
        else:
            participation.current_score = nouveau_score

    elif game.mode == "perso":
        # on additionne (High Score)
        participation.current_score += points

    # historique de la fléchette lancée
    db_throw = Throw(
        game_id=throw_in.game_id,
        player_username=throw_in.player_username,
        tour_number=throw_in.tour_number,
        dart_number=throw_in.dart_number,
        x_position=throw_in.x_position,
        y_position=throw_in.y_position,
        calculated_score=points,
        multiplier=multiplicateur # On enregistre le multiplicateur pour les stats 
    )

    # sauver dasn db
    session.add(db_throw)
    session.add(participation)
    session.add(game) # au cas ou on a change le statut de la partie à "finished"
    session.commit()
    session.refresh(db_throw)

    logger.info(f"Fléchette enregistrée ! {throw_in.player_username} a mis {points} points (Multiplicateur x{multiplicateur}). Nouveau score: {participation.current_score}")
    
    return db_throw