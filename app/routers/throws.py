import json
import logging
from datetime import datetime, timezone
from pydantic import BaseModel

from fastapi import APIRouter, Depends, HTTPException, Security
from fastapi.security.api_key import APIKeyHeader

from sqlmodel import Session, select, col 
from app.database import get_session

from app.models.throw import Throw, ThrowCreate, ThrowRead, ManualThrowCreate
from app.models.game import Game, GameStatus
from app.models.game_participation import GameParticipation, ValidationStatus
from app.models.player import Player
from app.models.target import Target

from app.config import RASPBERRY_API_KEY 
from app.security.auth import get_current_user
from app.utils.darts_logic import get_checkout_suggestion
from app.utils.dartboard_math import get_score_and_multiplier
from app.utils.led_controller import trigger_led_script 
from app.stream import stream_manager, broadcast_game_update 

from app.security.raspberry_pi import verify_raspberry_pi # pour sécuriser l'endpoint de réception des lancers, accessible uniquement par le Raspberry Pi autorisé

router = APIRouter(prefix="/throws", tags=["throws (Register only for Raspberry Pi)"])
logger = logging.getLogger(__name__)


# Fonction centrale du jeu : elle reçoit les infos d'un lancer, applique les règles du jeu 
# (bust, victoire, changement de joueur/tour) et crée le lancer dans la DB avec toutes les infos calculées.
#async def' car elle doit attendre l'envoi réseau des notifications SSE à la fin.
async def process_throw_logic(
    session: Session, 
    game: Game, 
    joueur_actuel: str, 
    tour_actuel: int, 
    flechette_actuelle: int, 
    points: int, 
    multiplicateur: int, 
    x_pos: float, 
    y_pos: float,
    camera_id: int | None = None):
    
    participation = session.get(GameParticipation, {"game_id": game.id, "player_username": joueur_actuel})
    total_points_flechette = points * multiplicateur
    
    is_bust = False
    is_victory = False

    # crée l'objet Throw immédiatement (mais on ne commit pas encore)
    db_throw = Throw(
        game_id=game.id,
        player_username=joueur_actuel,
        tour_number=tour_actuel,
        dart_number=flechette_actuelle,
        x_position=x_pos,
        y_position=y_pos,
        camera_id=camera_id,
        calculated_score=points,
        multiplier=multiplicateur
    )
    session.add(db_throw)

    # Logique spécifique aux modes 501 / 301
    if game.mode in ["501", "301"]:
        nouveau_score = participation.current_score - total_points_flechette
        
        # Vérif du BUST
        if nouveau_score < 0 or nouveau_score == 1 or (nouveau_score == 0 and multiplicateur != 2):
            is_bust = True
            logger.warning(f" BUST ! {joueur_actuel}. Retour à {participation.current_score}.")
            trigger_led_script("bust")
            
            # Correction BUG : annule les points du tour actuel (y compris multiplicateurs)
            previous_throws = session.exec(
                select(Throw).where(
                    Throw.game_id == game.id, 
                    Throw.player_username == joueur_actuel, 
                    Throw.tour_number == tour_actuel,
                    Throw.dart_number < flechette_actuelle # que les lancers précédents de ce tour
                )
            ).all()
            
            # remet le score tel qu'il était au début du tour
            # On compte les lancers déjà en DB + celui qu'on vient d'ajouter
            points_du_tour = sum(t.calculated_score * t.multiplier for t in previous_throws)
            
            participation.current_score += points_du_tour #correction bug
            
        # Vérif de la victoire (score doit être exactement à 0 avec un double)
        elif nouveau_score == 0 and multiplicateur == 2:
            is_victory = True
            logger.info(f" VICTOIRE ! {joueur_actuel} par un Double !")
            trigger_led_script("win")
            
            participation.current_score = 0
            participation.final_score = 0
            participation.position = 1 
            game.status = GameStatus.finished
            game.end_date = datetime.now(timezone.utc)
            
            # Classement auto des perdants
            autres = [p for p in game.participations if p.player_username != participation.player_username]
            autres.sort(key=lambda p: p.current_score)
            for i, perdant in enumerate(autres, start=2):
                perdant.final_score = perdant.current_score
                perdant.position = i
                session.add(perdant)
        else:
            participation.current_score = nouveau_score

    elif game.mode == "perso":
        participation.current_score += total_points_flechette

    #Recalcul du classement en temps réel 
        # Le plus gros score obtient la position 1 (reverse=True)
        participants_actifs = sorted(
            [p for p in game.participations if p.status != ValidationStatus.rejected],
            key=lambda p: p.current_score,
            reverse=True
        )
        for rank, p in enumerate(participants_actifs, start=1):
            p.position = rank
            session.add(p)
    
    # Gestion des animations LED 
    if not is_victory and not is_bust and flechette_actuelle == 3:
        # On récupère le score total du tour
        current_tour_throws = session.exec(
            select(Throw).where(
                Throw.game_id == game.id, 
                Throw.player_username == joueur_actuel, 
                Throw.tour_number == tour_actuel
            )
        ).all()
        tour_score = sum(t.calculated_score * t.multiplier for t in current_tour_throws)

        if tour_score == 180:
            trigger_led_script("score_180")
        elif tour_score >= 100:
            trigger_led_script("score_100")
        else:
            trigger_led_script("next_player")

    # Logique de transition de tour
    if not is_victory:
        if is_bust or flechette_actuelle == 3:
            # Passage au joueur suivant
            participants_actifs = sorted(
                [p for p in game.participations if p.status != ValidationStatus.rejected],
                key=lambda p: p.join_date
            )
            
            curr_idx = next(i for i, p in enumerate(participants_actifs) if p.player_username == joueur_actuel)
            next_idx = (curr_idx + 1) % len(participants_actifs)
            
            if next_idx == 0: # fini un cycle complet (Tous les joueurs ont joué 1 tour)
                if game.mode == "perso":
                    game.status = GameStatus.finished
                    game.end_date = datetime.now(timezone.utc)
                    for p in game.participations:
                        p.final_score = p.current_score
                        session.add(p)
                else:
                    game.current_turn_number += 1
            
            # passe au joueur suivant si la partie n'est pas finie
            if game.status != GameStatus.finished:
                game.current_player_username = participants_actifs[next_idx].player_username
                game.current_dart_number = 1

    game.last_interaction = datetime.now(timezone.utc)
    
    session.add(participation)
    session.add(game)
    session.commit()
    session.refresh(db_throw)
    
    await broadcast_game_update(game.id, session)
    return db_throw





#crée un modèle spécifique pour ce que le Raspberry va envoyer
class HardwareThrowPayload(BaseModel):
    target_id: str
    x_position: float
    y_position: float
    camera_id: int #1.2 ou 3 en fonction de la camera la plus precise

#Routes
#enregistrer un lancer de flechette
@router.post("/", response_model=ThrowRead) 
async def register_throw(
    throw_in: HardwareThrowPayload,
    session: Session = Depends(get_session),
    is_hardware_authorized: bool = Depends(verify_raspberry_pi)):
    
    
    # Log l'entrée brute (Ce que le Pi vient d'envoyer)
    logger.info(f" IMPACT REÇU [Cible: {throw_in.target_id}] - Caméra {throw_in.camera_id} - Pixels: (X:{throw_in.x_position}, Y:{throw_in.y_position})")
    
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
    logger.info(f" Tour de {joueur_actuel} (Tour n°{tour_actuel}, Fléchette {flechette_actuelle}/3)")

    # calcul des points
    points, multiplicateur = get_score_and_multiplier(throw_in.x_position, throw_in.y_position, camera_id=throw_in.camera_id)
    
    return await process_throw_logic(#ajout de await pour attendre que le broadcast se termine avant de répondre au Pi (pour éviter les problèmes de concurrence sur la DB)
        session, game, joueur_actuel, tour_actuel, flechette_actuelle,
        points, multiplicateur, throw_in.x_position, throw_in.y_position, throw_in.camera_id
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

    # x et y à 0 pour indiquer que c'est manuel
    db_throw = await process_throw_logic(#pareil que pour le register_throw, on attend que le broadcast se termine avant de répondre au téléphone pour éviter les problèmes de concurrence sur la DB
        session, game, joueur_actuel, tour_actuel, flechette_actuelle,
        points, multiplicateur, 0.0, 0.0, None
    )
    
    logger.info(f"Lancer MANUEL enregistré par {current_user.username} : {points} points.")
    return db_throw



#route pour annuler le dernier lancer !! (en cas de defaillance technique ou erreur de score)
@router.delete("/undo/{game_id}")
async def undo_last_throw(
    game_id: int,
    session: Session = Depends(get_session),
    current_user: Player = Depends(get_current_user)):
    
    game = session.get(Game, game_id)
    if not game:
        raise HTTPException(status_code=404, detail="Partie introuvable.")

    # vérif que la personne qui annule joue bien dans partie
    is_participant = any(p.player_username == current_user.username for p in game.participations)
    if not is_participant and not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Vous ne participez pas à cette partie.")

    #cherche le DERNIER lancer enregistré pour cette partie
    last_throw = session.exec(
        select(Throw)
        .where(Throw.game_id == game_id)
        .order_by(col(Throw.id).desc())
    ).first()

    if not last_throw:
        raise HTTPException(status_code=400, detail="Aucun lancer à annuler dans cette partie.")

    joueur_concerne = last_throw.player_username

    # supp ce lancer de la base de données
    session.delete(last_throw)
    
    # restaure les pointeurs du jeu (-> à qui le tour ?)
    game.current_player_username = joueur_concerne
    game.current_turn_number = last_throw.tour_number
    game.current_dart_number = last_throw.dart_number
    
    # Si la partie était finie (le lancer annulé était la victoire), on la relance 
    if game.status == GameStatus.finished:
        game.status = GameStatus.in_progress
        game.end_date = None
        # efface les final_score et positions de tout le monde
        for p in game.participations:
            p.final_score = None
            p.position = None
            session.add(p)

    # recalcul du score parfait de ce joueur depuis le début
    participation = next(p for p in game.participations if p.player_username == joueur_concerne)
    
    remaining_throws = session.exec(
        select(Throw)
        .where(Throw.game_id == game_id)
        .where(Throw.player_username == joueur_concerne)
        .order_by(Throw.id)
    ).all()

    if game.mode in ["501", "301"]:
        start_score = int(game.mode)
        current_score = start_score
        
        #simule les tours un par un pour gérer correctement les "vieux busts"
        throws_by_turn : dict[int, list[Throw]]= {}
        
        for t in remaining_throws:
            if t.tour_number not in throws_by_turn:
                throws_by_turn[t.tour_number] = []
            throws_by_turn[t.tour_number].append(t) 
            
        for tour in sorted(throws_by_turn.keys()):
            tour_throws = throws_by_turn[tour]
            
            tour_score = sum(t.calculated_score * t.multiplier for t in tour_throws)
            temp_score = current_score - tour_score
            
            last_t = tour_throws[-1]
            # Vérif du BUST
            if temp_score < 0 or temp_score == 1 or (temp_score == 0 and last_t.multiplier != 2):
                pass # BUST : valide pas le score du tour
            else:
                current_score = temp_score # Valide
                
        participation.current_score = current_score

    elif game.mode == "perso":
        participation.current_score = sum(t.calculated_score * t.multiplier for t in remaining_throws)
        
        participants_actifs = sorted(
            [p for p in game.participations if p.status != ValidationStatus.rejected],
            key=lambda p: p.current_score,
            reverse=True
        )
        for rank, p in enumerate(participants_actifs, start=1):
            p.position = rank
            session.add(p)
            
    session.add(participation)
    session.add(game)
    session.commit()
    
    logger.info(f"Lancer annulé par {current_user.username}. Retour au joueur {joueur_concerne} (Fléchette {last_throw.dart_number}).")
    
    await broadcast_game_update(game.id, session)
    
    return {"message": "Dernier lancer annulé avec succès."}


