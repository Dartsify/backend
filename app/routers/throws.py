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

router = APIRouter(prefix="/throws", tags=["throws (Register only for Raspberry Pi)"])
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
    is_hardware_authorized: bool = Depends(verify_raspberry_pi)
):
    # recup la partie
    game = session.get(Game, throw_in.game_id)
    if not game or game.status != GameStatus.in_progress:
        raise HTTPException(status_code=400, detail="Partie introuvable ou terminée.")

    # deduction de qui doit jouer
    joueur_actuel = game.current_player_username
    tour_actuel = game.current_turn_number
    flechette_actuelle = game.current_dart_number

    participation = session.get(GameParticipation, {"game_id": game.id, "player_username": joueur_actuel})

    # calcul des points
    points, multiplicateur = get_score_and_multiplier(throw_in.x_position, throw_in.y_position)
    
    # Règles du jeu et Bust
    is_bust = False
    is_victory = False

    if game.mode in ["501", "301"]:
        nouveau_score = participation.current_score - points
        
        if nouveau_score < 0 or nouveau_score == 1 or (nouveau_score == 0 and multiplicateur != 2):
            is_bust = True
            
            # Annulation des points
            previous_throws = session.exec(
                select(Throw).where(Throw.game_id == game.id, Throw.player_username == joueur_actuel, Throw.tour_number == tour_actuel)
            ).all()
            
            points_a_annuler = sum(t.calculated_score for t in previous_throws)
            participation.current_score += points_a_annuler            
            
        elif nouveau_score == 0 and multiplicateur == 2:
            is_victory = True
            participation.current_score = 0
            game.status = GameStatus.finished
        else:
            participation.current_score = nouveau_score
            
    elif game.mode == "perso":
        participation.current_score += points

    # crée le lancer dans db avec les infos qu'on a déduites
    db_throw = Throw(
        game_id=game.id,
        player_username=joueur_actuel,
        tour_number=tour_actuel,
        dart_number=flechette_actuelle,
        x_position=throw_in.x_position,
        y_position=throw_in.y_position,
        calculated_score=points,
        multiplier=multiplicateur
    )
    session.add(db_throw)

    #intelligence du tour
    if not is_victory:
        fin_de_tour = is_bust or (flechette_actuelle == 3)

        if fin_de_tour:
            # cherche qui est le joueur suivant
            participants = game.participations
            current_idx = next(i for i, p in enumerate(participants) if p.player_username == joueur_actuel)
            next_idx = current_idx + 1
            
            # Si on a fait le tour de tous les joueurs (Fin de la manche)
            if next_idx >= len(participants):
                if game.mode == "perso":
                    #mode perso doit s'arrete
                    game.status = GameStatus.finished
                    logger.info("Fin de la partie Mode Perso ! Tout le monde a lancé ses 3 fléchettes.")
                else:
                    # Pour le 501/301, on passe au tour suivant
                    next_idx = 0 
                    game.current_turn_number += 1 
                    game.current_player_username = participants[next_idx].player_username
                    game.current_dart_number = 1
                    logger.info(f"Nouveau tour ! C'est à {game.current_player_username}.")
            else:
                # passe au joueur suivant dans le MÊME tour
                game.current_player_username = participants[next_idx].player_username
                game.current_dart_number = 1
                logger.info(f"Fin de tour. C'est maintenant à {game.current_player_username} de jouer !")
        else:
            # passe juste à la fléchette suivante
            game.current_dart_number += 1

    session.add(participation)
    session.add(game)
    session.commit()
    session.refresh(db_throw)

    return db_throw



from app.security.auth import get_current_user
from app.models.throw import ManualThrowCreate
#route pour rentrer son score manuellement si defaillance technique
@router.post("/manual", response_model=ThrowRead)
def register_manual_throw(
    throw_in: ManualThrowCreate,
    session: Session = Depends(get_session),
    current_user: Player = Depends(get_current_user)):
    
    game = session.get(Game, throw_in.game_id)
    if not game or game.status != GameStatus.in_progress:
        raise HTTPException(status_code=400, detail="Partie introuvable ou terminée.")

    # secu pour verifie que celui qui clique participe bien à la partie (hote ou joueur de celle ci)
    is_participant = any(p.player_username == current_user.username for p in game.participations)
    
    if not is_participant:
        raise HTTPException(status_code=403, detail="Vous ne participez pas à cette partie, vous ne pouvez pas modifier le score.")
    
    joueur_actuel = game.current_player_username
    tour_actuel = game.current_turn_number
    flechette_actuelle = game.current_dart_number

    participation = session.get(GameParticipation, {"game_id": game.id, "player_username": joueur_actuel})

    # utilise les points envoye par le téléphone
    points = throw_in.points
    multiplicateur = throw_in.multiplier

    #rappel des regles du jeu
    is_bust = False
    is_victory = False

    if game.mode in ["501", "301"]:
        nouveau_score = participation.current_score - points
        
        if nouveau_score < 0 or nouveau_score == 1 or (nouveau_score == 0 and multiplicateur != 2):
            is_bust = True
            
            previous_throws = session.exec(
                select(Throw).where(Throw.game_id == game.id, Throw.player_username == joueur_actuel, Throw.tour_number == tour_actuel)
            ).all()
            
            points_a_annuler = sum(t.calculated_score for t in previous_throws)
            participation.current_score += points_a_annuler            
            
        elif nouveau_score == 0 and multiplicateur == 2:
            is_victory = True
            participation.current_score = 0
            game.status = GameStatus.finished
        else:
            participation.current_score = nouveau_score
            
    elif game.mode == "perso":
        participation.current_score += points

    # On crée le lancer "manuel" (on met X et Y à 0 pour indiquer que c'est manuel)
    db_throw = Throw(
        game_id=game.id,
        player_username=joueur_actuel,
        tour_number=tour_actuel,
        dart_number=flechette_actuelle,
        x_position=0.0,
        y_position=0.0,
        calculated_score=points,
        multiplier=multiplicateur
    )
    session.add(db_throw)

    if not is_victory:
        fin_de_tour = is_bust or (flechette_actuelle == 3)

        if fin_de_tour:
            participants_actifs = [p for p in game.participations if p.status == "validated"]
            current_idx = next(i for i, p in enumerate(participants_actifs) if p.player_username == joueur_actuel)
            next_idx = current_idx + 1
            
            if next_idx >= len(participants_actifs):
                if game.mode == "perso":
                    game.status = GameStatus.finished
                else:
                    next_idx = 0 
                    game.current_turn_number += 1 
                    game.current_player_username = participants_actifs[next_idx].player_username
                    game.current_dart_number = 1
            else:
                game.current_player_username = participants_actifs[next_idx].player_username
                game.current_dart_number = 1
        else:
            game.current_dart_number += 1

    session.add(participation)
    session.add(game)
    session.commit()
    session.refresh(db_throw)

    logger.info(f"Lancer MANUEL enregistré par {current_user.username} : {points} points.")
    return db_throw