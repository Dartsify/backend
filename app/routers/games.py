from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select
import logging
from typing import List, Optional
from app.database import get_session
from app.models.game import Game, GameCreate, GameRead, GameStatus
from app.models.target import Target
from app.models.game_participation import GameParticipation, ValidationStatus
from app.models.player import Player, Friendship
from app.security.auth import get_current_user
from datetime import datetime

from pydantic import BaseModel

from app.utils.darts_logic import get_checkout_suggestion

router = APIRouter(prefix="/games", tags=["games"])
logger = logging.getLogger(__name__)



#creer une partie
@router.post("/", response_model=GameRead)
def create_new_game(
    game_in: GameCreate,
    session: Session = Depends(get_session),
    current_user: Player = Depends(get_current_user)): # Le joueur doit être connecté
    
    logger.info(f"Le joueur {current_user.username} tente de lancer un {game_in.mode} sur la cible {game_in.target_id}")

    # Verif que cible scannée existe bien dans la DB
    target = session.get(Target, game_in.target_id)
    if not target:
        raise HTTPException(status_code=404, detail="Cible introuvable. Veuillez scanner un QR Code valide.")

    # secu: On cherche s'il y a déjà une partie non terminée sur cette cible
    active_game = session.exec(
        select(Game)
        .where(Game.target_id == game_in.target_id)
        .where(Game.status != GameStatus.finished)).first() # On bloque si une partie est pas finished 

    if active_game:
        logger.warning(f"La cible {game_in.target_id} est déjà occupée par la partie {active_game.id}.")
        # On renvoie l'erreur au format tableau pour le Front
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
    elif game_in.mode == "Perso":
        starting_score = 0 #mode pour jury , demarre a 0 et essai d'etre le plus eleve
    else :
        starting_score = 0   
    
    participation = GameParticipation(
        game_id=new_game.id,
        player_username=current_user.username,
        current_score=starting_score,
        status = ValidationStatus.validated
    )
    session.add(participation)
    session.commit()

    logger.info(f"Partie {new_game.id} créée avec succès. {current_user.username} a rejoint la partie.")
    return new_game




#modèle Pydantic juste pour recevoir le pseudo de l'ami à inviter
class PlayerInvite(BaseModel):
    username: str
    

from app.models.player import FriendshipStatus

#route pour ajouter joueur (ami) a la partie
@router.post("/{game_id}/add_player")
def add_player_to_game(
    game_id: int,
    invite: PlayerInvite,
    session: Session = Depends(get_session),
    current_user: Player = Depends(get_current_user)): # Le joueur qui invite doit être connecte
    
    # vérif si partie existe
    game = session.get(Game, game_id)
    if not game:
        raise HTTPException(status_code=404, detail="Partie introuvable.")

    if game.status != GameStatus.waiting:
        raise HTTPException(status_code=400, detail="Impossible de rejoindre une partie terminée ou en cours.")

    

    # verif si joueur qui invite fait bien partie de ce jeu (Seul l'hôte/un participant peut inviter d'autres)
    host_participation = session.get(GameParticipation, {"game_id": game_id, "player_username": current_user.username})
    if not host_participation:
        raise HTTPException(status_code=403, detail="Vous ne pouvez pas inviter de joueurs dans une partie à laquelle vous ne participez pas.")

    #verif si l'ami invite existe deja dans la base de donnees
    friend = session.get(Player, invite.username)
    if not friend:
        raise HTTPException(status_code=404, detail=f"Le joueur '{invite.username}' n'existe pas. Dites lui de se créer un compte !")

    
    #vérifie si une ligne existe dans la table Friendship entre les deux joueurs
    is_friend = session.exec(
        select(Friendship).where(
            (((Friendship.user_username == current_user.username) & (Friendship.friend_username == friend.username)) |
            ((Friendship.user_username == friend.username) & (Friendship.friend_username == current_user.username))) &
            (Friendship.status == FriendshipStatus.accepted) 
        )
    ).first()
    
    if not is_friend:
        raise HTTPException(
            status_code=403, 
            detail=f"Vous ne pouvez pas inviter {friend.username} car il/elle n'est pas dans votre liste d'amis !"
        )
    
    
    # Verif que l'ami n'est pas DÉJÀ dans la partie
    existing_participation = session.get(GameParticipation, {"game_id": game_id, "player_username": invite.username})
    if existing_participation:
        raise HTTPException(status_code=400, detail=f"Le joueur '{invite.username}' est déjà dans cette partie.")

    # Ajuster son scor de depart en fonction du mode
    if game.mode == "501":
        starting_score = 501
    elif game.mode == "301":
        starting_score = 301
    else: # mode "perso" (pour le jury)
        starting_score = 0

    # ajouter l'ami à la partie 
    new_participation = GameParticipation(
        game_id=game.id,
        player_username=friend.username,
        current_score=starting_score,
        status=ValidationStatus.pending
    )
    
    #chrono reboot
    game.last_interaction = datetime.utcnow()
    session.add(game)
    
    session.add(new_participation)
    session.commit()

    logger.info(f"Le joueur {friend.username} a été ajouté à la partie {game.id} par {current_user.username}.")
    
    return {
        "message": f"{friend.username} a rejoint la partie avec succès !",
        "game_id": game.id,
        "player": friend.username,
        "starting_score": starting_score
    }
    



# Route pour ACCEPTER (Valider) sa participation
@router.post("/{game_id}/validate")
def validate_participation(
    game_id: int, 
    session: Session = Depends(get_session),
    current_user: Player = Depends(get_current_user)
):
    participation = session.get(GameParticipation, {"game_id": game_id, "player_username": current_user.username})
    
    if not participation:
        raise HTTPException(status_code=404, detail="Participation introuvable.")
    if participation.status == ValidationStatus.validated:
        raise HTTPException(status_code=400, detail="Partie déjà validée.")

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
    current_user: Player = Depends(get_current_user)
):
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
from app.models.game_participation import GameParticipationRead, GameReadWithParticipants
@router.get("/{game_id}", response_model=GameReadWithParticipants,response_model_exclude={"id"} )
def get_game_state(
    game_id: int,
    session: Session = Depends(get_session),
    current_user: Player = Depends(get_current_user)): # Il faut être connecté

    # On récupère la partie
    game = session.get(Game, game_id)
    if not game:
        raise HTTPException(status_code=404, detail="Partie introuvable.")

    #verif si joueur fait partie de la partie (securite) (a enlever si affichage sur un autre ecran par ex)
    is_participant = any(p.player_username == current_user.username for p in game.participations)
    if not is_participant and not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Vous ne participez pas à cette partie.")
    
    # transforme l'objet db "game" en un simple dictionnaire
    game_dict = game.model_dump()
    
    # Quand la partie est en 'waiting', l'hôte est toujours stocké dans current_player_username.
    # Si la partie a commencé, on prend par défaut le premier joueur de la liste (le créateur).
    host_username = game.current_player_username if game.status == GameStatus.waiting else game.participations[0].player_username
    
    # recréer la liste des participants avec suggestions
    participations_enrichies = []
    
    for p in game.participations:
        #transforme la ligne du participant en dictionnaire
        p_dict = p.model_dump()
        
        # Grâce à la relation Relationship, SQLModel va chercher le profil du joueur
        if p.player:
            p_dict["player_name"] = p.player.name #affiche le nom du joueur pour le front
        else:
            p_dict["player_name"] = "Joueur inconnu"
            
        p_dict["is_host"] = (p.player_username == host_username)
        
        if game.status == GameStatus.waiting:
            darts_left = 3
        else:
            darts_left = 4 - game.current_dart_number # si le tour 1 est en cours, current_dart_number = 1 donc darts_left = 3, etc.
        
        
        # ajout de suggestion calculée
        if game.mode in ["501", "301"]:
            p_dict["checkout_suggestion"] = get_checkout_suggestion(p.current_score, darts_left)
        else:
            p_dict["checkout_suggestion"] = [] # Pas de suggestion pour le mode perso
        
        participations_enrichies.append(p_dict)

    #remplace la vieille liste de base de données par notre nouvelle liste enrichie
    game_dict["participations"] = participations_enrichies

    # FastAPI va lire 'response_model=GameReadWithParticipants' et s'occuper du formatage final
    return game_dict


from fastapi import Query
#Route pour lister toutes les parties (historique de ses propres parties en tant que joueur)
# et si admin il a les parties de tout le monde
@router.get("/", response_model=List[GameRead])
def get_all_games(
    limit: int = 50,
    offset: int = 0,
    status: Optional[List[GameStatus]] = Query(None, description="Filtrer par statut (waiting, in_progress, finished)"),
    session: Session = Depends(get_session),
    current_user: Player = Depends(get_current_user)):
    
    # base de la requête selon le rôle (Admin ou Joueur)
    if current_user.is_admin:
        # L'admin a accès à TOUTES les parties
        query = select(Game).order_by(Game.start_date.desc())
    else:
        # Le joueur ne voit que SES parties (jointure)
        query = (
            select(Game)
            .join(GameParticipation)
            .where(GameParticipation.player_username == current_user.username)
            .order_by(Game.start_date.desc())
        )
    
    #filtrage multiple
    if status:
        # ".in_()" est la commande SQL pour dire "Si le statut du jeu FAIT PARTIE de la liste demandée"
        query = query.where(Game.status.in_(status))
        
    query = query.offset(offset).limit(limit)
    games = session.exec(query).all()
    
    return games
    
    
#route pour lancer la partie qui a ete cree et qui est en mode waiting (l'hote clique sur "commencer la partie" quand tout le monde est la)
@router.post("/{game_id}/start", response_model=GameRead)
def launch_game(
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

    #Go
    game.status = GameStatus.in_progress
    
    #chrono reinitialise
    game.last_interaction = datetime.utcnow()
    
    session.add(game)
    session.commit()
    session.refresh(game)

    logger.info(f"La partie {game.id} passe en IN_PROGRESS ! Que le meilleur gagne.")
    
    return game


from pydantic import BaseModel
import random
from typing import Optional
from app.security.auth import get_current_user_optional

#modèle d'entrée : le prénom n'est requis que pour les invités
class JoinGameRequest(BaseModel):
    name: Optional[str] = None 

#route pour rejoindre la partie en tant que joueur (en scannant le QR code de la cible)(in,vite ou non)
@router.post("/{game_id}/join")
def join_game(
    game_id: int, 
    join_in: JoinGameRequest, 
    session: Session = Depends(get_session),
    current_user: Optional[Player] = Depends(get_current_user_optional)):
    
    # Vérif de la salle d'attente
    game = session.get(Game, game_id)
    if not game or game.status != GameStatus.waiting:
        raise HTTPException(status_code=400, detail="Partie introuvable ou a déjà commencé.")

    #scenario A : le joueur est connecte a son compte
    if current_user:
        # Sécu : Vérifie s'il n'est pas DÉJÀ dans la partie
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
    game.last_interaction = datetime.utcnow()
    session.add(game)
    
    session.commit()

    logger.info(f"{display_name} a rejoint la partie {game.id}.")
    
    return {
        "message": f"Bienvenue {display_name}, vous avez rejoint la partie !",
        "game_id": game.id,
        "username": username_to_add,
        "starting_score": starting_score
    }
    
    

#route pour supp un joueur dans le lobby de la partie (seulement en wwaiting et seul l'hote peut le faire)
@router.delete("/{game_id}/participants/{username_to_remove}")
def kick_player_from_game(
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

    logger.info(f"Le joueur {username_to_remove} a été expulsé de la partie {game_id} par l'hôte {current_user.username}.")
    
    return {"message": f"Le joueur a été expulsé avec succès de la partie."}


#modele pour changer le mode si indecis avant de start la partie
class GameModeUpdate(BaseModel):
    mode: str # "501", "301", ou "perso"

#fonction pour changer le mode de la partie avant lancement
@router.patch("/{game_id}/mode")
def change_game_mode(
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

    
    game.last_interaction = datetime.utcnow()
    session.add(game)
    session.commit()

    logger.info(f"L'hôte {current_user.username} a changé le mode de la partie {game.id} en {game.mode}.")

    return {
        "message": f"Le mode de jeu a été changé en {game.mode}.",
        "new_mode": game.mode,
        "new_starting_score": new_starting_score
    }
    
    
    
from app.stream import stream_manager
import json
import asyncio
from fastapi import Request
from fastapi.responses import StreamingResponse

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
                
                # On attend qu'un message arrive dans la boîte (ex: une fléchette lancée)
                # asyncio.wait_for permet de verifier regulierement si client toujours la
                try:
                    message = await asyncio.wait_for(q.get(), timeout=1.0) #await sur la boîte aux lettres, timeout d'1 seconde pour vérifier régulièrement la connexion du client
                    # On formate selon la norme SSE exacte : "data: le_message\n\n"
                    yield f"data: {message}\n\n"
                except asyncio.TimeoutError:
                    # Timeout d'1 seconde normal, on recommence la boucle pour vérifier request.is_disconnected()
                    continue
                    
        finally:
            # Si le téléphone (appareil) coupe la connexion, on supprime sa "boîte aux lettres"
            stream_manager.remove_listener(game_id, q)

    # On renvoie la réponse au format 'text/event-stream'
    return StreamingResponse(event_generator(), media_type="text/event-stream")