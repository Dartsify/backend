from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select
import logging
from typing import List
from app.database import get_session
from app.models.game import Game, GameCreate, GameRead, GameStatus
from app.models.target import Target
from app.models.game_participation import GameParticipation, ValidationStatus
from app.models.player import Player, Friendship
from app.security.auth import get_current_user

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
@router.post("/{id}/add_player")
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
@router.post("/{id}/validate")
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
@router.post("/{id}/reject")
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
@router.get("/{id}", response_model=GameReadWithParticipants)
def get_game_state(
    game_id: int,
    session: Session = Depends(get_session),
    current_user: Player = Depends(get_current_user) # Il faut être connecté
):
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
    
    # recréer la liste des participants avec suggestions
    participations_enrichies = []
    
    for p in game.participations:
        #transforme la ligne du participant en dictionnaire
        p_dict = p.model_dump()
        
        # ajout de suggestion calculée
        if game.mode in ["501", "301"]:
            p_dict["checkout_suggestion"] = get_checkout_suggestion(p.current_score)
        else:
            p_dict["checkout_suggestion"] = [] # Pas de suggestion pour le mode perso
        
        participations_enrichies.append(p_dict)

    #remplace la vieille liste de base de données par notre nouvelle liste enrichie
    game_dict["participations"] = participations_enrichies

    # FastAPI va lire 'response_model=GameReadWithParticipants' et s'occuper du formatage final
    return game_dict


#Route pour lister toutes les parties (historique de ses propres parties en tant que joueur)
# et si admin il a les parties de tout le monde
@router.get("/", response_model=List[GameRead])
def get_all_games(
    limit: int = 50,
    offset: int = 0,
    session: Session = Depends(get_session),
    current_user: Player = Depends(get_current_user)):
    
    if current_user.is_admin:
        # L'admin voit tout (avec un tri par date décroissante pour avoir les plus récentes d'abord)
        games = session.exec(
            select(Game)
            .order_by(Game.start_date.desc())
            .offset(offset)
            .limit(limit)).all()
        return games
    else:
        # Le joueur normal ne voit que les parties auxquelles il a participé
        #(JOIN entre la table Game et GameParticipation)
        games = session.exec(
            select(Game)
            .join(GameParticipation)
            .where(GameParticipation.player_username == current_user.username)
            .order_by(Game.start_date.desc())
            .offset(offset)
            .limit(limit)).all()
        return games
    
    
#route pour lancer la partie qui a ete cree et qui est en mode waiting (l'hote clique sur "commencer la partie" quand tout le monde est la)
@router.post("/{id}/start", response_model=GameRead)
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
    
    session.add(game)
    session.commit()
    session.refresh(game)

    logger.info(f"La partie {game.id} passe en IN_PROGRESS ! Que le meilleur gagne.")
    
    return game