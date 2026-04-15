import json
import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Security
from fastapi.security.api_key import APIKeyHeader

from sqlmodel import Session, select
from app.database import get_session

from app.models.throw import Throw, ThrowCreate, ThrowRead, ManualThrowCreate
from app.models.game import Game, GameStatus
from app.models.game_participation import GameParticipation, ValidationStatus
from app.models.player import Player
from app.models.target import Target

from app.config import RASPBERRY_API_KEY # La clé secrète que le Raspberry Pi doit utiliser pour s'authentifier
from app.security.auth import get_current_user
from app.utils.darts_logic import get_checkout_suggestion
from app.utils.dartboard_math import get_score_and_multiplier
from app.utils.led_controller import trigger_led_script # pour lancer les animations LED sur le Raspberry Pi après un bust ou une victoire
from app.stream import stream_manager, broadcast_game_update # pour envoyer les notifications SSE aux téléphones après chaque lancer


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




# Fonction centrale du jeu : elle reçoit les infos d'un lancer, applique les règles du jeu 
# (bust, victoire, changement de joueur/tour) et crée le lancer dans la DB avec toutes les infos calculées.
#async def' car elle doit attendre l'envoi réseau des notifications SSE à la fin.
async def process_throw_logic( #async pour faire la transmission SSE après le traitement du lancer, et await pour attendre que la transmission se termine avant de répondre au téléphone 
    session: Session, 
    game: Game, 
    joueur_actuel: str, 
    tour_actuel: int, 
    flechette_actuelle: int, 
    points: int, 
    multiplicateur: int, 
    x_pos: float, 
    y_pos: float
) -> Throw:
    
    participation = session.get(GameParticipation, {"game_id": game.id, "player_username": joueur_actuel})

    total_points_flechette = points * multiplicateur
    
    # Règles du jeu et Bust
    is_bust = False
    is_victory = False

    if game.mode in ["501", "301"]:
        nouveau_score = participation.current_score - total_points_flechette
        
        if nouveau_score < 0 or nouveau_score == 1 or (nouveau_score == 0 and multiplicateur != 2):
            is_bust = True
            
            trigger_led_script("bust") #lance l'animation de bust sur le Raspberry Pi
            
            # Annulation des points
            previous_throws = session.exec(
                select(Throw).where(Throw.game_id == game.id, Throw.player_username == joueur_actuel, Throw.tour_number == tour_actuel)).all()
            
            points_a_annuler = sum(t.calculated_score for t in previous_throws)
            participation.current_score += points_a_annuler            
            
        elif nouveau_score == 0 and multiplicateur == 2:
            is_victory = True
            
            trigger_led_script("win") #lance l'animation de victoire sur le Raspberry Pi

            
            participation.current_score = 0
            participation.final_score = 0
            participation.position = 1 
            game.status = GameStatus.finished
            
            game.end_date = datetime.utcnow() # On enregistre l'heure de la victoire 
            
            #classement des perdants (pour mathias)
            autres_joueurs = [p for p in game.participations if p.player_username != participation.player_username]
            autres_joueurs.sort(key=lambda p: p.current_score)
            
            place_actuelle = 2
            for perdant in autres_joueurs:
                perdant.final_score = perdant.current_score
                perdant.position = place_actuelle
                session.add(perdant)
                place_actuelle += 1
                
        else:
            participation.current_score = nouveau_score
            
    elif game.mode == "perso":
        participation.current_score += total_points_flechette

    # crée le lancer dans db avec les infos qu'on a déduites
    db_throw = Throw(
        game_id=game.id,
        player_username=joueur_actuel,
        tour_number=tour_actuel,
        dart_number=flechette_actuelle,
        x_position=x_pos,
        y_position=y_pos,
        calculated_score=points,
        multiplier=multiplicateur
    )
    session.add(db_throw)
    
    #gestion des animations led pour 100+, 180 et next player
    if not is_victory and not is_bust:
        if flechette_actuelle == 3:
            # récup les lancers précédents de ce tour pour calculer le total
            previous_throws = session.exec(
                select(Throw).where(Throw.game_id == game.id, Throw.player_username == joueur_actuel, Throw.tour_number == tour_actuel)
            ).all()
            
            # LE VRAI SCORE DU TOUR (Lancers précédents multipliés + lancer actuel multiplié)
            tour_score = sum(t.calculated_score * t.multiplier for t in previous_throws) + total_points_flechette
            
            if tour_score == 180:
                trigger_led_script("score_180")
            elif tour_score >= 100:
                trigger_led_script("score_100")
            else:
                trigger_led_script("next_player")


    #intelligence du tour
    if not is_victory:
        fin_de_tour = is_bust or (flechette_actuelle == 3)

        if fin_de_tour:
            #prendre que les joueurs validés
            participants_actifs = [p for p in game.participations if p.status != ValidationStatus.rejected]
            
            # tri chronologique
            participants_actifs = sorted(participants_actifs, key=lambda p: p.join_date)
            
            current_idx = next(i for i, p in enumerate(participants_actifs) if p.player_username == joueur_actuel)
            next_idx = current_idx + 1
            
            # Si on a fait le tour de tous les joueurs (Fin de la manche)
            if next_idx >= len(participants_actifs):
                if game.mode == "perso":
                    #mode perso doit s'arrete
                    game.status = GameStatus.finished
                    game.end_date = datetime.utcnow() # On enregistre l'heure de fin
                    
                    # récup tous les joueurs de la partie et trie les scores pour distribuer les places (1er, 2eme, 3eme...)
                    tous_les_joueurs = game.participations
                    tous_les_joueurs.sort(key=lambda p: p.current_score, reverse=True)
                    
                    place_actuelle = 1
                    for joueur in tous_les_joueurs:
                        joueur.final_score = joueur.current_score #  fige le score final
                        joueur.position = place_actuelle          # attribue le classement
                        session.add(joueur)
                        place_actuelle += 1
                        
                    logger.info("Fin de la partie Mode Perso ! Tout le monde a lancé ses 3 fléchettes.")
                else:
                    # Pour le 501/301, on passe au tour suivant
                    next_idx = 0 
                    game.current_turn_number += 1 
                    game.current_player_username = participants_actifs[next_idx].player_username
                    game.current_dart_number = 1
                    logger.info(f"Nouveau tour ! C'est à {game.current_player_username}.")
            else:
                # passe au joueur suivant dans le MÊME tour
                game.current_player_username = participants_actifs[next_idx].player_username
                game.current_dart_number = 1
                logger.info(f"Fin de tour. C'est maintenant à {game.current_player_username} de jouer !")
        else:
            # passe juste à la fléchette suivante
            game.current_dart_number += 1

    #reinitialise le compteur d'inactivire à chaque lancer
    game.last_interaction = datetime.utcnow()
    
    session.add(participation)
    session.add(game)
    session.commit()
    session.refresh(db_throw)
    
    # SSE : Un seul appel propre 
    await broadcast_game_update(game.id, session)
    return db_throw




from pydantic import BaseModel
#crée un modèle spécifique pour ce que le Raspberry va envoyer
class HardwareThrowPayload(BaseModel):
    target_id: str
    x_position: float
    y_position: float

#Routes
#enregistrer un lancer de flechette
@router.post("/", response_model=ThrowRead) 
async def register_throw(
    throw_in: HardwareThrowPayload,
    session: Session = Depends(get_session),
    is_hardware_authorized: bool = Depends(verify_raspberry_pi)):
    
    #new logique
    #recherche multi cible (si bar a plusieurs cibles)
    # On cherche la partie en cours SUR LA CIBLE qui vient d'envoyer le message
    game = session.exec(
        select(Game)
        .where(Game.target_id == throw_in.target_id) # Filtre par cible
        .where(Game.status == GameStatus.in_progress) # Filtre par statut
    ).first()

    if not game:
        logger.warning(f"Une fléchette a touché la cible {throw_in.target_id}, mais aucune partie n'est en cours !")
        raise HTTPException(status_code=400, detail="Aucune partie en cours sur cette cible.")

    # deduction de qui doit jouer
    joueur_actuel = game.current_player_username
    tour_actuel = game.current_turn_number
    flechette_actuelle = game.current_dart_number

    # calcul des points
    points, multiplicateur = get_score_and_multiplier(throw_in.x_position, throw_in.y_position)
    
    # On délègue toute l'intelligence au moteur central 
    return await process_throw_logic(#ajout de await pour attendre que le broadcast se termine avant de répondre au Pi (pour éviter les problèmes de concurrence sur la DB)
        session, game, joueur_actuel, tour_actuel, flechette_actuelle,
        points, multiplicateur, throw_in.x_position, throw_in.y_position
    )




#route pour rentrer son score manuellement si defaillance technique
@router.post("/manual", response_model=ThrowRead)
async def register_manual_throw(
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

    # utilise les points envoye par le téléphone
    points = throw_in.points
    multiplicateur = throw_in.multiplier

    # On délègue au moteur central (avec x et y à 0 pour indiquer que c'est manuel) !
    db_throw = await process_throw_logic(#pareil que pour le register_throw, on attend que le broadcast se termine avant de répondre au téléphone pour éviter les problèmes de concurrence sur la DB
        session, game, joueur_actuel, tour_actuel, flechette_actuelle,
        points, multiplicateur, 0.0, 0.0
    )
    
    logger.info(f"Lancer MANUEL enregistré par {current_user.username} : {points} points.")
    return db_throw



