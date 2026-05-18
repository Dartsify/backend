from fastapi import APIRouter, Depends, HTTPException
import json
import random
import logging
import asyncio
import threading
from datetime import datetime, timezone
from typing import List, Optional, Dict, Any

from pydantic import BaseModel

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from sqlmodel import Session, select, func, col 
from app.database import get_session

import sys
from pathlib import Path
sys.path.append(str(Path(__file__).resolve().parents[3]))
import threading
from algoIA.main_DEBUG import main as algo_ia_main

from app.models.game import Game, GameCreate, GameRead, GameStatus, GameListResponse
from app.models.game_participation import GameParticipation, ValidationStatus, GameReadWithParticipants
from app.models.player import Player, Friendship, FriendshipStatus
from app.models.target import Target
from app.models.throw import Throw

from app.security.auth import get_current_user, get_current_user_optional, create_access_token
from app.utils.darts_logic import get_checkout_suggestion
from app.utils.led_controller import trigger_led_script
from app.utils.game_state import build_base_game_state
from app.stream import stream_manager

from app.stream import broadcast_game_update 

#config du router et du logger
router = APIRouter(prefix="/games", tags=["games"])
logger = logging.getLogger(__name__)

# Variable globale pour l'IA
_ia_thread = None


#creer une partie
@router.post("/", response_model=GameRead)
def create_new_game(
    game_in: GameCreate,
    session: Session = Depends(get_session),
    current_user: Player = Depends(get_current_user)): # Le joueur doit être connecté
    
    logger.info(f"Le joueur {current_user.username} tente de lancer un {game_in.mode} sur la cible {game_in.target_id}")

    # Verif que cible scannée existe dans la DB
    target = session.get(Target, game_in.target_id)
    if not target:
        raise HTTPException(status_code=404, detail="Cible introuvable. Veuillez scanner un QR Code valide.")

    # secu: cherche s'il y a déjà une partie non terminée sur cette cible
    active_game = session.exec(
        select(Game)
        .where(Game.target_id == game_in.target_id)
        .where(Game.status != GameStatus.finished)).first() # bloque si une partie est pas finished 

    if active_game:
        logger.warning(f"La cible {game_in.target_id} est déjà occupée par la partie {active_game.id}.")
        raise HTTPException(
            status_code=400, 
            detail=[
                {
                    "field": "target_id", 
                    "value": game_in.target_id, 
                    "message": "Cette cible est déjà en cours d'utilisation par d'autres joueurs."
                }
            ]
        )

    # Créer la nouvelle partie
    new_game = Game(
        mode=game_in.mode,
        target_id=game_in.target_id,
        status=GameStatus.waiting, # On démarre en "waiting" pour que les joueurs puissent rejoindre avant de commencer
        current_player_username=current_user.username
    )
    
    session.add(new_game)
    session.commit()
    session.refresh(new_game) # refresh pour que SQLite génère l'ID de la partie 

    # Lier le joueur à la partie et lui donner son score de départ
    # logique : si c'est un 501, il commence à 501
    if game_in.mode == "501":
        starting_score = 501
    elif game_in.mode == "301" :
        starting_score = 301
    elif game_in.mode == "perso":
        starting_score = 0 #mode pour jury , demarre a 0 et essai d'etre le plus eleve
    else :
        raise HTTPException(
            status_code=400, 
            detail=[
                {
                    "field": "game_mode", 
                    "value": game_in.mode, 
                    "message": "Ce mode n'existe pas. Choisissez parmi : 501, 301 ou perso."
                }
            ]
        )  
    
    participation = GameParticipation(
        game_id=new_game.id,
        player_username=current_user.username,
        current_score=starting_score,
        status = ValidationStatus.validated
    )
    session.add(participation)
    session.commit()
    
    trigger_led_script("lobby")#lance l'animation de salle d'attente (lobby) sur le Raspberry Pi

    logger.info(f"Partie {new_game.id} créée avec succès. {current_user.username} a rejoint la partie.")
    return new_game




#Route pour lister toutes les parties (historique de ses propres parties en tant que joueur)
# et si admin il a les parties de tout le monde
@router.get("/", response_model=List[GameListResponse])
def get_all_games(
    limit: int = 50,
    offset: int = 0,
    status: Optional[List[GameStatus]] = Query(None, description="Filtrer par statut (waiting, in_progress, finished)"),
    session: Session = Depends(get_session),
    current_user: Player = Depends(get_current_user)):
    
    # base de la requête selon le rôle (Admin ou Joueur)
    if current_user.is_admin:
        # L'admin a accès à TOUTES les parties
        query = select(Game).order_by(Game.creation_date.desc())
    else:
        # Le joueur ne voit que SES parties 
        query = (
            select(Game)
            .join(GameParticipation)
            .where(GameParticipation.player_username == current_user.username)
            .order_by(Game.creation_date.desc())
        )
    
    if status:
        # ".in_()" est la commande SQL pour dire "Si le statut du jeu FAIT PARTIE de la liste demandée"
        query = query.where(Game.status.in_(status))
        
    query = query.offset(offset).limit(limit)
    games = session.exec(query).all()
    
    enriched_games = []
    
    for game in games:
        game_dict = game.model_dump()
        
        # ifos de la cible
        target = session.get(Target, game.target_id)
        if target:
            game_dict["target_name"] = target.name
            game_dict["target_location"] = target.location
        else:
            game_dict["target_name"] = "Cible inconnue"
            game_dict["target_location"] = "Lieu inconnu"
            
        #nbr joueurs
        game_dict["player_count"] = len(game.participations)
        
        # gagnant si partie finie
        game_dict["winner_username"] = None  
        game_dict["winner_name"] = None
        
        if game.status == GameStatus.finished:
            # Cherche le joueur qui a la position "1"
            winner = next((p for p in game.participations if p.position == 1), None)
            if winner:
                game_dict["winner_username"] = winner.player_username
                # essaie de récupérer le vrai prénom, sinon met "Inconnu"
                game_dict["winner_name"] = winner.player.name if winner.player else "Joueur inconnu"
                
        enriched_games.append(game_dict)
        
    return enriched_games
        
    
    


#route pour que le joueur voit ses historiques de parties jouees avec un ami ou a un endroit sur la base d'n filtre 
@router.get("/my_history")
def get_my_game_history(
    location: str | None = None,
    friends: List[str] | None = Query(default=None),
    session: Session = Depends(get_session),
    current_user: Player = Depends(get_current_user)):
    
    
    # Base : cherche les participations de l'utilisateur actuel
    # jointure pour récupérer les objets "Game" directement
    query = (
        select(Game)
        .join(GameParticipation)
        .where(GameParticipation.player_username == current_user.username)
        .where(Game.status == GameStatus.finished) # passé
    )

    # filtre par lieu (recherche textuelle sur le nom ou la ville de la cible)
    if location:
        query = query.join(Target, Game.target_id == Target.id).where(
            col(Target.location).ilike(f"%{location}%") | 
            col(Target.name).ilike(f"%{location}%")
        )

    # Filtre par amis (Parties jouées avec X et Y)
    if friends:
        for friend_username in friends:
            query = query.where(
                col(Game.id).in_(
                    select(GameParticipation.game_id)
                    .where(GameParticipation.player_username == friend_username)
                )
            )

    #tri par date
    query = query.order_by(col(Game.end_date).desc())

    results = session.exec(query).all()
    
    return results




class ZoneStatBreakdown(BaseModel):
    zone: str
    total_hits: int
    number: Dict[str, int] 
    
    
#nouveau modele apres demande du front pour afficher les ppd et score max d'un tour
class PlayerGamePerformance(BaseModel):
    username: str
    player_name: str
    average_per_dart: float
    max_turn_score: int

class GameStatsResponse(BaseModel):
    game_id: int
    zone_stats: List[ZoneStatBreakdown]
    player_performances: List[PlayerGamePerformance] # new
    

#recup les stats de la game qui vient d'etre terminee pour tous les joueurs
@router.get("/{game_id}/stats", response_model=GameStatsResponse)
def get_single_game_stats(
    game_id: int,
    session: Session = Depends(get_session)):
        
    game = session.get(Game, game_id)
    if not game:
        raise HTTPException(status_code=404, detail="Partie introuvable.")

    # calcul des stats de zones (Heatmap)
    hits_query = session.exec(
        select(Throw.calculated_score, Throw.multiplier, Throw.player_username, func.count(Throw.id).label("hits"))
        .where(Throw.game_id == game_id)
        .where(Throw.x_position != 0.0) # ignore les lancers manuels pour la précision
        .group_by(Throw.calculated_score, Throw.multiplier, Throw.player_username)
    ).all()

    zones_dict = {}

    for row in hits_query:
        score = row[0]
        mult = row[1]
        username = row[2] 
        hits = row[3]
        
        if score == 0:
            label = "Miss"
        elif score == 25:
            label = "Double Bullseye" if mult == 2 else "Bullseye"
        else:
            if mult == 3: label = f"T{score}"
            elif mult == 2: label = f"D{score}"
            else: label = f"{score}"

        if label not in zones_dict:
            zones_dict[label] = {"zone": label, "total_hits": 0, "number": {}}
        
        zones_dict[label]["total_hits"] += hits
        zones_dict[label]["number"][username] = hits

    sorted_zones = sorted(list(zones_dict.values()), key=lambda x: x["total_hits"], reverse=True)

    #calcul de moyenne et max pour un tour
    # récup TOUS les lancers de la partie (y compris les lancers manuels ici car ca intervient dans les score moyens par ex)
    all_throws = session.exec(
        select(Throw).where(Throw.game_id == game_id)
    ).all()

    # Dict temporaire pour stocker les calculs
    calc_dict = {}
    
    for p in game.participations:
        calc_dict[p.player_username] = {
            "player_name": p.player.name if p.player and p.player.name else p.player_username,
            "total_score": 0,
            "total_darts": 0,
            "turns": {}
        }

    for t in all_throws:
        user = t.player_username
        if user not in calc_dict:
            continue
            
        points = t.calculated_score * t.multiplier
        tour = t.tour_number
        
        calc_dict[user]["total_score"] += points
        calc_dict[user]["total_darts"] += 1
        
        # additionne les points de ce tour précis
        if tour not in calc_dict[user]["turns"]:
            calc_dict[user]["turns"][tour] = 0
        calc_dict[user]["turns"][tour] += points

    player_performances = []
    for user, data in calc_dict.items():
        # Moyenne
        avg = round(data["total_score"] / data["total_darts"], 2) if data["total_darts"] > 0 else 0.0
        
        # Score max par tour
        max_turn = max(data["turns"].values()) if data["turns"] else 0
        
        player_performances.append(
            PlayerGamePerformance(
                username=user,
                player_name=data["player_name"],
                average_per_dart=avg,
                max_turn_score=max_turn
            )
        )

    return GameStatsResponse(
        game_id=game_id,
        zone_stats=sorted_zones,
        player_performances=player_performances
    )
    



#modèle Pydantic juste pour recevoir les pseudo des ami à inviter
class PlayerInvites(BaseModel):
    usernames: List[str]
    

#route pour ajouter joueur (ami) a la partie
@router.post("/{game_id}/add_players")
async def add_players_to_game(
    game_id: int,
    invites: PlayerInvites,
    session: Session = Depends(get_session),
    current_user: Player = Depends(get_current_user)): 
    
    game = session.get(Game, game_id)
    if not game:
        raise HTTPException(status_code=404, detail="Partie introuvable.")

    if game.status != GameStatus.waiting:
        raise HTTPException(status_code=400, detail="Impossible de rejoindre une partie terminée ou en cours.")

    # secu: l'utilisateur doit faire partie de la game pour inviter
    host_participation = session.get(GameParticipation, {"game_id": game_id, "player_username": current_user.username})
    if not host_participation:
        raise HTTPException(status_code=403, detail="Vous ne pouvez pas inviter de joueurs dans une partie à laquelle vous ne participez pas.")

    #seul l'hote a le droit d'ajouter des amis
    if game.current_player_username != current_user.username:
        raise HTTPException(status_code=403, detail="Seul l'hôte de la partie peut inviter des amis.")
    
    if game.mode == "501":
        starting_score = 501
    elif game.mode == "301":
        starting_score = 301
    else: 
        starting_score = 0

    added_players = []

    for username in invites.usernames:
        friend = session.get(Player, username)
        if not friend:
            continue

        #verif si amis ou non (on n'invite que les amis)
        is_friend = session.exec(
            select(Friendship).where(
                (((Friendship.user_username == current_user.username) & (Friendship.friend_username == friend.username)) |
                ((Friendship.user_username == friend.username) & (Friendship.friend_username == current_user.username))) &
                (Friendship.status == FriendshipStatus.accepted)
            )
        ).first()
        
        if not is_friend:
            continue
        
        existing_participation = session.get(GameParticipation, {"game_id": game_id, "player_username": friend.username})
        if existing_participation:
            continue

        #creat
        new_participation = GameParticipation(
            game_id=game.id,
            player_username=friend.username,
            current_score=starting_score,
            status=ValidationStatus.pending
        )
        session.add(new_participation)
        added_players.append(friend.username)

    if added_players:
        game.last_interaction = datetime.now(timezone.utc)#maj du chrono d'inactivité
        session.add(game)
        session.commit()
        
        trigger_led_script("player_join") #lance l'animation de bienvenue sur le Raspberry Pi pour signaler que des joueurs ont rejoint la partie
        logger.info(f"Les joueurs {added_players} ont été ajoutés à la partie {game.id} par {current_user.username}.")
        
        # SSE
        await broadcast_game_update(game_id, session)
    
    return {
        "message": f"{len(added_players)} ami(s) a/ont rejoint la partie avec succès !",
        "game_id": game.id,
        "added_players": added_players,
        "starting_score": starting_score
    }
    



# Route pour ACCEPTER (Valider) sa participation
@router.post("/{game_id}/validate")
def validate_participation(
    game_id: int, 
    session: Session = Depends(get_session),
    current_user: Player = Depends(get_current_user)):
    
    participation = session.get(GameParticipation, {"game_id": game_id, "player_username": current_user.username})
    
    if not participation:
        raise HTTPException(status_code=404, detail="Participation introuvable.")
    if participation.status == ValidationStatus.validated:
        raise HTTPException(status_code=400, detail="Partie déjà validée.")

    #passe le statu en valideé pour que le joueur puisse jouer et que sa partie compte pour les stats
    participation.status = ValidationStatus.validated
    session.add(participation)
    session.commit()
    
    logger.info(f"Le joueur {current_user.username} a validé sa participation à la partie {game_id}.")
    return {"message": "Partie validée avec succès ! Les statistiques comptent désormais pour votre profil."}




# Route pour REFUSER (Rejeter) sa participation
@router.post("/{game_id}/reject")
def reject_participation(
    game_id: int, 
    session: Session = Depends(get_session),
    current_user: Player = Depends(get_current_user)):
    
    participation = session.get(GameParticipation, {"game_id": game_id, "player_username": current_user.username})
    
    if not participation:
        raise HTTPException(status_code=404, detail="Participation introuvable.")

    # On passe en rejected (on ne supprime pas (throw) pour ne pas casser la partie)
    participation.status = ValidationStatus.rejected
    session.add(participation)
    session.commit()
    
    logger.info(f"Le joueur {current_user.username} a refusé sa participation à la partie {game_id}.")
    return {"message": "Partie refusée. Elle n'impactera pas vos statistiques."}





#Route pour voir lobby (voir quels joueurs sont la pour debut de partie)
#on initialise donc la partie ici
#Pour la modif des scores et le jeu il faut aller dans app.routers.throws)
@router.get("/{game_id}", response_model=GameReadWithParticipants, response_model_exclude={"id"})
def get_game_state(
    game_id: int,
    session: Session = Depends(get_session),
    current_user: Player = Depends(get_current_user)):

    # récup la base commune
    game_dict = build_base_game_state(game_id, session)
    if not game_dict:
        raise HTTPException(status_code=404, detail="Partie introuvable.")

    # On ajoute la personnalisation "is_friend" (car on sait qui regarde ici)
    for p_dict in game_dict["participations"]:
        if p_dict["player_username"] == current_user.username:
            p_dict["is_friend"] = False
        else:
            is_friend_db = session.exec(
                select(Friendship).where(
                    (((Friendship.user_username == current_user.username) & (Friendship.friend_username == p_dict["player_username"])) |
                    ((Friendship.user_username == p_dict["player_username"]) & (Friendship.friend_username == current_user.username))) &
                    (Friendship.status == FriendshipStatus.accepted)
                )
            ).first()
            p_dict["is_friend"] = True if is_friend_db else False

    return game_dict





    
#route pour lancer la partie qui a ete cree et qui est en mode waiting (l'hote clique sur "commencer la partie" quand tout le monde est la)
@router.post("/{game_id}/start", response_model=GameRead)
async def launch_game(
    game_id: int,
    session: Session = Depends(get_session),
    current_user: Player = Depends(get_current_user)):
    
    
    # récupère la partie
    game = session.get(Game, game_id)
    if not game:
        raise HTTPException(status_code=404, detail="Partie introuvable.")

    # Sécu: Est-ce que c'est bien l'HÔTE qui essaie de démarrer ?
    # (L'hôte est le joueur actuel tant que le tour 1 n'a pas commencé)
    if game.current_player_username != current_user.username:
        raise HTTPException(
            status_code=403, 
            detail="Seul l'hôte (créateur de la partie) peut lancer le jeu."
        )

    # dans la salle d'attente ?
    if game.status != GameStatus.waiting:
        raise HTTPException(
            status_code=400, 
            detail="Cette partie a déjà commencé ou est déjà terminée."
        )

    # Démarrer l'algorithme IA s'il ne tourne pas déjà
    global _ia_thread
    if _ia_thread is None or not _ia_thread.is_alive():
        logger.info("Démarrage de l'algorithme IA pour la partie...")
        _ia_thread = threading.Thread(target=algo_ia_main, daemon=True)
        _ia_thread.start()

    #Go
    game.status = GameStatus.in_progress
    
    # fige l'heure exacte du début de la partie
    game.start_date = datetime.now(timezone.utc)
    
    trigger_led_script("start_round")
    logger.info(f" Lancement de la partie {game_id} ! Mode: {game.mode}. Que le meilleur gagne.") #lance l'animation de lancement sur le Raspberry Pi
    
    #chrono reinitialise
    game.last_interaction = datetime.now(timezone.utc)
    
    session.add(game)
    session.commit()
    session.refresh(game)

    logger.info(f"La partie {game.id} passe en IN_PROGRESS ! Que le meilleur gagne.")
    
    #ajout avec async pour update en temps reel dans le lobby :
    await broadcast_game_update(game_id, session)
    
    return game




#modèle d'entrée : le prénom n'est requis que pour les invités
class JoinGameRequest(BaseModel):
    name: Optional[str] = None 


#route pour rejoindre la partie en tant que joueur (en scannant le QR code de la cible)(in,vite ou non)
@router.post("/{game_id}/join")
async def join_game(
    game_id: int, 
    join_in: JoinGameRequest, 
    session: Session = Depends(get_session),
    current_user: Optional[Player] = Depends(get_current_user_optional)):
    
    # Vérif de la salle d'attente
    game = session.get(Game, game_id)
    if not game or game.status != GameStatus.waiting:
        raise HTTPException(status_code=400, detail="La partie est introuvable ou a déjà commencé.")

    #scenario A : le joueur est connecte a son compte
    if current_user:
        # Sécu : verif s'il n'est pas DÉJÀ dans la partie
        existing_p = session.get(GameParticipation, {"game_id": game_id, "player_username": current_user.username})
        if existing_p:
            return {"message": "Vous êtes déjà dans la salle d'attente !"}
        
        username_to_add = current_user.username
        display_name = current_user.username
        status_to_add = ValidationStatus.validated # On valide direct

    # Scenario B : Pas connecte -> invité
    else:
        if not join_in.name:
            raise HTTPException(status_code=400, detail="Veuillez fournir un prénom pour rejoindre en tant qu'invité.")
        
        # Création du profil fantôme
        while True:
            random_suffix = random.randint(10000, 99999)
            guest_username = f"guest_{random_suffix}"
            if not session.get(Player, guest_username):
                break

        db_guest = Player(username=guest_username, name=join_in.name, is_guest=True)
        session.add(db_guest)
        
        username_to_add = guest_username
        display_name = join_in.name
        status_to_add = ValidationStatus.validated
        
        #creation d'un token d'acces pour l'invite pour que front pusse appele la route protegee get game id
        access_token = create_access_token(data={"sub": guest_username})

    #on associe le joueur (invite ou non) à la partie avec le score de départ en fonction du mode de jeu
    starting_score = 501 if game.mode == "501" else (301 if game.mode == "301" else 0)

    new_participation = GameParticipation(
        game_id=game.id,
        player_username=username_to_add,
        current_score=starting_score,
        status=status_to_add
    )
    session.add(new_participation)

    # chrono d'inactivité
    game.last_interaction = datetime.now(timezone.utc)
    session.add(game)
    session.commit()
    
    trigger_led_script("player_join") #lance l'animation de bienvenue sur le Raspberry Pi

    logger.info(f"{display_name} a rejoint la partie {game.id}.")
    
    #  crie dans"le mégaphone"pour tous ceux qui sont dans le lobby
    await broadcast_game_update(game_id, session)
    
    
    reponse_front = {
        "message": f"Bienvenue {display_name}, vous avez rejoint la partie !",
        "game_id": game.id,
        "username": username_to_add,
        "starting_score": starting_score
    }
    
    # Si c'est un invité, on glisse le token dans la réponse
    if not current_user:
        reponse_front["access_token"] = access_token
        reponse_front["token_type"] = "bearer"
        
    return reponse_front
    
    


#route pour supp un joueur dans le lobby de la partie (seulement en wwaiting et seul l'hote peut le faire)
@router.delete("/{game_id}/participants/{username_to_remove}")
async def kick_player_from_game(
    game_id: int,
    username_to_remove: str,
    session: Session = Depends(get_session),
    current_user: Player = Depends(get_current_user)):
    
    # cherche partie
    game = session.get(Game, game_id)
    if not game:
        raise HTTPException(status_code=404, detail="Partie introuvable.")

    # verif si waiting
    if game.status != GameStatus.waiting:
        raise HTTPException(
            status_code=400, 
            detail="Impossible d'expulser un joueur : la partie a déjà commencé ou est terminée."
        )

    # seul l'hote peut le faire
    if game.current_player_username != current_user.username:
        raise HTTPException(
            status_code=403, 
            detail="Seul le créateur de la partie (l'hôte) peut expulser des joueurs."
        )

    if username_to_remove == current_user.username:
        raise HTTPException(
            status_code=400, 
            detail="Vous ne pouvez pas vous expulser vous-même de votre propre partie !"
        )

    #verif si le joueur a supp est bien dans  la game
    participation = session.exec(
        select(GameParticipation)
        .where(GameParticipation.game_id == game_id)
        .where(GameParticipation.player_username == username_to_remove)).first()

    if not participation:
        raise HTTPException(
            status_code=404, 
            detail=f"Le joueur {username_to_remove} n'est pas dans la salle d'attente."
        )

    session.delete(participation)
    session.commit()
    
    trigger_led_script("player_leave")

    logger.info(f"Le joueur {username_to_remove} a été expulsé de la partie {game_id} par l'hôte {current_user.username}.")
    
    #ajout avec le async:
    # SSE : Un seul appel propre
    await broadcast_game_update(game_id, session)
    
    return {"message": f"Le joueur a été expulsé avec succès de la partie."}




#modele pour changer le mode si indecis avant de start la partie
class GameModeUpdate(BaseModel):
    mode: str # "501", "301", ou "perso"


#fonction pour changer le mode de la partie avant lancement
@router.patch("/{game_id}/mode")
async def change_game_mode(
    game_id: int,
    mode_update: GameModeUpdate,
    session: Session = Depends(get_session),
    current_user: Player = Depends(get_current_user)):
    
    game = session.get(Game, game_id)
    if not game:
        raise HTTPException(status_code=404, detail="Partie introuvable.")

    # Uniquement dans la salle d'attente
    if game.status != GameStatus.waiting:
        raise HTTPException(
            status_code=400, 
            detail="Impossible de changer de mode : la partie a déjà commencé ou est terminée."
        )

    # Seul l'hôte peut décider de changer le mode
    if game.current_player_username != current_user.username:
        raise HTTPException(
            status_code=403, 
            detail="Seul le créateur de la partie (l'hôte) peut changer le mode de jeu."
        )

    game.mode = mode_update.mode

    if game.mode == "501":
        new_starting_score = 501
    elif game.mode == "301":
        new_starting_score = 301
    else:
        new_starting_score = 0

    # maj des scores de tout le monde
    for participation in game.participations:
        participation.current_score = new_starting_score
        session.add(participation)

    
    game.last_interaction = datetime.now(timezone.utc) #maj du chrono d'inactivité
    session.add(game)
    session.commit()

    logger.info(f"L'hôte {current_user.username} a changé le mode de la partie {game.id} en {game.mode}.")
    
    #ajout avec le async pour update en temps reel dans le lobby :
    # SSE : Un seul appel propre
    await broadcast_game_update(game_id, session)
    
    
    return {
        "message": f"Le mode de jeu a été changé en {game.mode}.",
        "new_mode": game.mode,
        "new_starting_score": new_starting_score
    }
    
    
    

#route pour le stream de la partie (SSE) : le front-end reste connecté ici pour recevoir les mises à jour en temps réel
@router.get("/{game_id}/stream")
async def game_stream(game_id: int, request: Request):    
    
    async def event_generator():
        # On donne une "boîte aux lettres" à cet appareil 
        q = stream_manager.add_listener(game_id)
        try:
            while True:
                # Si le client s'est déconnecté (fermé l'app), on arrête la boucle
                if await request.is_disconnected():
                    break
                
                #  attend qu'un message arrive dans la boîte (ex: une fléchette lancée)
                # asyncio.wait_for permet de verifier regulierement si client toujours la
                try:
                    message = await asyncio.wait_for(q.get(), timeout=1.0) #await sur la boîte aux lettres, timeout d'1 seconde pour vérifier régulièrement la connexion du client
                    # formate selon la norme SSE exacte : "data: le_message\n\n"
                    yield f"data: {message}\n\n"
                except asyncio.TimeoutError:
                    # Timeout d'1 seconde normal, on recommence la boucle pour vérifier request.is_disconnected()
                    continue
                    
        finally:
            # Si le téléphone (appareil) coupe la connexion, on supprime sa "boîte aux lettres"
            stream_manager.remove_listener(game_id, q)

    # renvoie la réponse au format 'text/event-stream'
    return StreamingResponse(event_generator(), media_type="text/event-stream")




#route ppour quitter une partie sois meme:
@router.post("/{game_id}/leave")
async def leave_game(
    game_id: int,
    session: Session = Depends(get_session),
    current_user: Player = Depends(get_current_user)):
    
    game = session.get(Game, game_id)
    if not game:
        raise HTTPException(status_code=404, detail="Partie introuvable.")

    #Vérif que joueur est bien dans cette partie
    participation = next((p for p in game.participations if p.player_username == current_user.username), None)
    if not participation:
        raise HTTPException(status_code=400, detail="Vous ne participez pas à cette partie.")

    # idd l'hote
    host_username = game.current_player_username if game.status == GameStatus.waiting else game.participations[0].player_username
    is_host = (current_user.username == host_username)

    # scenario si l'hote quitte : on clôture la partie et on prévient tout le monde
    if is_host:
        # libère la cible
        game.status = GameStatus.finished
        
        game.end_date = datetime.now(timezone.utc) # Fin prématurée de la partie
        trigger_led_script("unused") #lance l'animation de libération de la cible sur le Raspberry Pi
        
        session.add(game)
        session.commit()
        
        logger.info(f"L'hôte {current_user.username} a quitté. La partie {game_id} est clôturée.")
        
        # previens tous via le SSE que la partie est finie
        await broadcast_game_update(game_id, session)
        
        trigger_led_script("unused") #lance l'animation de libération de la cible sur le Raspberry Pi
        
        return {"message": "Vous avez quitté la partie. En tant qu'hôte, la salle a été fermée."}
        
    #scenario si un random quitte
    else:
        # On le supprime simplement de la partie
        session.delete(participation)
        session.commit()
        session.refresh(game) # Met à jour l'objet game pour le SSE
        
        logger.info(f"Le joueur {current_user.username} a quitté la partie {game_id}.")
        
        # ASTUCE POUR LE SSE :
        # Comme on vient de se supprimer de la partie, si on appelle get_game_state avec 'current_user',
        # notre propre sécurité va nous renvoyer une erreur 403 (Accès Refusé) car on n'est plus dans la partie.
        # On utilise donc le profil de l'hôte (qui est toujours là) pour générer l'état de la partie.
        
        await broadcast_game_update(game_id, session)
                
        return {"message": "Vous avez quitté la partie avec succès."}




class GuestInvites(BaseModel):
    guest_names: List[str] # Le front enverra {"guest_names": ["Michel", "Hubert"]}
    
    


@router.post("/{game_id}/add_guests")
async def add_guests_to_game(
    game_id: int,
    guests: GuestInvites, 
    session: Session = Depends(get_session),
    current_user: Player = Depends(get_current_user)):
    
    game = session.get(Game, game_id)
    if not game:
        raise HTTPException(status_code=404, detail="Partie introuvable.")

    if game.status != GameStatus.waiting:
        raise HTTPException(status_code=400, detail="Impossible d'ajouter des invités dans une partie terminée ou en cours.")

    host_participation = session.get(GameParticipation, {"game_id": game_id, "player_username": current_user.username})
    if not host_participation:
        raise HTTPException(status_code=403, detail="Vous ne participez pas à cette partie.")
        
    # secu : Est-ce que le joueur est bien l'hôte ? (le current_player de la table Game)
    if game.current_player_username != current_user.username:
        raise HTTPException(status_code=403, detail="Seul l'hôte de la partie peut ajouter des invités manuellement.")

    if game.mode == "501":
        starting_score = 501
    elif game.mode == "301":
        starting_score = 301
    else: 
        starting_score = 0

    added_guests = []

    for guest_name in guests.guest_names:
        
        random_digits = random.randint(10000, 99999)
        guest_username = f"guest_{random_digits}"
        
        while session.get(Player, guest_username):
            random_digits = random.randint(10000, 99999)
            guest_username = f"guest_{random_digits}"

        new_guest = Player(
            username=guest_username,
            name=guest_name,
            email=f"{guest_username}@guest.dartsify.com", 
            password="GUEST_NO_PASSWORD", 
            is_guest=True
        )
        session.add(new_guest)
        
        new_participation = GameParticipation(
            game_id=game.id,
            player_username=guest_username,
            current_score=starting_score,
            status=ValidationStatus.validated 
        )
        session.add(new_participation)
        
        added_guests.append({
            "username": guest_username,
            "name": guest_name
        })

    if added_guests:
        game.last_interaction = datetime.now(timezone.utc) #maj du chrono d'inactivité
        session.add(game)
        session.commit()
        logger.info(f"Les invités {added_guests} ont été ajoutés à la partie {game.id} par {current_user.username}.")
        
        #SSE
        await broadcast_game_update(game_id, session)
    
    return {
        "message": f"{len(added_guests)} invité(s) ajouté(s) avec succès !",
        "game_id": game.id,
        "added_guests": added_guests, 
        "starting_score": starting_score
    }
    


