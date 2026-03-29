from typing import Annotated, List
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session, select
from datetime import datetime
import logging

from app.database import SessionDep, get_session 
from app.models.player import PasswordUpdate, PlayerStats, Player, PlayerPublic, PlayerCreate, PlayerRead, PlayerUpdate

from app.security.auth import hash_password, get_current_user, verify_password

router = APIRouter(prefix="/players", tags=["players"]) #creation route
logger = logging.getLogger(__name__) # Récupère le logger configuré

#Creer un joueur
@router.post("/", response_model=PlayerRead)
def create_player(player: PlayerCreate, session: Session = Depends(get_session)):
    
    logger.info(f"Tentative de création du joueur : {player.username}")
    
    #interdire le mot guest dans le pseudo (car réservé pour les comptes invités)
    if "guest" in player.username.lower():
        logger.warning(f"Création refusée : le pseudo '{player.username}' contient le mot réservé 'guest'.")
        raise HTTPException(
            status_code=400, 
            detail="Le pseudo ne peut pas contenir le mot 'guest', qui est réservé aux comptes invités."
        )
    
    #forcer email en minuscule avant les verif
    player.email = player.email.lower()
    
    # Vérifier si pseudo existe déjà 
    existing_player = session.get(Player, player.username)
    if existing_player:
        logger.error("Le pseudo qui essaie d'être créé est déjà pris ! ")
        raise HTTPException(status_code=400, detail="Ce pseudo est déjà pris.")
    
    #verif si email existe deja a un autre joueur
    existing_email = session.exec(select(Player).where(Player.email == player.email)).first()
    if existing_email:
        raise HTTPException(status_code=400, detail="Cet email est déjà utilisé par un autre compte.")
    
    hashed_pw = hash_password(player.password)
    
    db_player = Player (
        username=player.username,
        email=player.email,
        name=player.name,
        age=player.age,
        creation_date=datetime.utcnow(),
        hashed_password=hashed_pw
    )
    session.add(db_player)
    try:
        session.commit()
    except Exception as e:
        session.rollback()
        logger.error(f"Échec de la création du joueur {player.username}. Erreur : {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))
    session.refresh(db_player)
    logger.info(f"Joueur {player.username} créé avec succès.")
    return db_player


#Lire son propre profil ->route protégée
#mettre /me avant {username} pour que FastAPI ne confonde pas les 2routes
@router.get("/me", response_model=PlayerRead)
def read_current_player(current_user: Player=Depends(get_current_user)):
    return current_user#si token valide on a direct le joueur


#Lire tous les joueurs (avec offset) -> seulement admin
@router.get("/", response_model=List[PlayerPublic])
def get_players(
    offset: int = Query(0, ge=0, description="Décalage pour pagination"),
    limit: int = Query(100, le=100, description="Nombre max de joueurs à retourner"),
    session: Session = Depends(get_session),
    current_user: Player = Depends(get_current_user)):
    
    if not current_user.is_admin:
        raise HTTPException(
            status_code=403, 
            detail="Accès refusé. Seuls les administrateurs peuvent voir la liste des joueurs."
        )
    
    players = session.exec(select(Player).offset(offset).limit(limit)).all()
    logger.info(f"Liste des joueurs retournée avec succès. ")
    return players



# #Modifier un joueur (update)-> protégé car ca doit etre son propre profil
@router.patch("/me", response_model=PlayerRead)
def update_current_player(
    player_update: PlayerUpdate,
    session: Session = Depends(get_session),
    current_user: Player = Depends(get_current_user)):
    
    # On met à jour uniquement les champs envoyés
    update_data = player_update.model_dump(exclude_unset=True)
    current_user.sqlmodel_update(update_data)

    session.add(current_user)
    session.commit()
    session.refresh(current_user)
    
    logger.info(f"Le joueur {current_user.username} a mis à jour son profil.")
    return current_user


#Route pour changement de mot de passe
@router.patch("/me/password")
def update_password(
    password_data: PasswordUpdate,
    session: Session = Depends(get_session),
    current_user: Player = Depends(get_current_user)):
        
    # verif que joueur connaît mdp actuel
    if not verify_password(password_data.old_password, current_user.hashed_password):
        logger.warning(f"Tentative de changement de mot de passe échouée pour {current_user.username} (Mauvais ancien mot de passe).")
        raise HTTPException(status_code=400, detail="L'ancien mot de passe est incorrect.")
        # raise HTTPException(
        #     status_code=400,
        #     detail=[
        #         {
        #             "Field": "old_password",
        #             "Value": password_update.old_password,
        #             "Message": "L'ancien mot de passe est incorrect."
        #         }
        #     ]
        # )
    
    
    #hache le nouveau mdp et maj de db
    current_user.hashed_password = hash_password(password_data.new_password)
    
    session.add(current_user)
    session.commit()
    
    logger.info(f"Le joueur {current_user.username} a modifié son mot de passe avec succès.")
    
    #front devra deco et reco l'utilisateur    
    return {"message": "Mot de passe modifié avec succès. Veuillez vous reconnecter."}



from app.models.game import Game, GameStatus
# #Supprimer un joueur(delete)->protégé (ca doit etre son profil a lui)
@router.delete("/me")
def delete_current_player(
    session: Session = Depends(get_session),
    current_user: Player = Depends(get_current_user)):
    
    # verif si le joueur est dans une partie "in_progress" -> eviter de faire crash la partie
    # s'il est dedans
    partie_en_cours = session.exec(
        select(GameParticipation)
        .join(Game)
        .where(GameParticipation.player_username == current_user.username)
        .where(Game.status == GameStatus.in_progress)).first()

    if partie_en_cours:
        raise HTTPException(
            status_code=400, 
            detail="Impossible de supprimer votre compte pendant une partie en cours. Terminez ou quittez la partie d'abord."
        )
    
    
    # Nettoyage de sécurité : On supprime d'abord ses participations 
    # pour éviter l'erreur de clé primaire (AssertionError)
    participations = session.exec(
        select(GameParticipation).where(GameParticipation.player_username == current_user.username)
    ).all()
    for p in participations:
        session.delete(p)
        
    #  upprime aussi tous ses lancers (Throws)
    throws = session.exec(
        select(Throw).where(Throw.player_username == current_user.username)
    ).all()
    for t in throws:
        session.delete(t)
        
    session.delete(current_user)
    session.commit()
    
    logger.info(f"Le joueur {current_user.username} a supprimé son compte et son historique.")
    return {"ok": True, "message": "Votre compte a été supprimé avec succès."}



from app.models.game_participation import GameParticipation, ValidationStatus
# Route pour voir ses invitations en attente (notification)
@router.get("/me/pending")
def get_pending_invitations(
    session: Session = Depends(get_session),
    current_user: Player = Depends(get_current_user)
):
    from sqlmodel import select
    
    # On cherche toutes les participations du joueur qui sont en "pending"
    pending = session.exec(
        select(GameParticipation)
        .where(GameParticipation.player_username == current_user.username)
        .where(GameParticipation.status == ValidationStatus.pending)
    ).all()
    
    return pending

# #Lire un player spécifique basé sur son username -> admin
@router.get("/{username}", response_model=PlayerPublic)
def read_player(username: str,
                session: Session = Depends(get_session),
                current_user: Player = Depends(get_current_user)):
    
    if not current_user.is_admin:
        raise HTTPException(
            status_code=403, 
            detail="Accès refusé. Seuls les administrateurs peuvent cherhcer un joueur basé sur son username."
        )
    
    player = session.get(Player, username)
    if not player:
        raise HTTPException(status_code=404, detail=f"Player {username} not found")
    return player


from sqlmodel import func , desc
from app.models.throw import Throw
#Route pour avoir les stats perso du joueur
@router.get("/me/stats", response_model=PlayerStats)
def get_my_stats(
    session: Session = Depends(get_session),
    current_user: Player = Depends(get_current_user)):
    
    # calcul du nombre de parties jouées (validées)
    total_games = session.exec(
        select(func.count())
        .select_from(GameParticipation)
        .where(GameParticipation.player_username == current_user.username)
        .where(GameParticipation.status == ValidationStatus.validated)
    ).one()

    # Calcul du nombre de victoires (position 1)
    total_wins = session.exec(
        select(func.count())
        .select_from(GameParticipation)
        .where(GameParticipation.player_username == current_user.username)
        .where(GameParticipation.status == ValidationStatus.validated)
        .where(GameParticipation.position == 1)
    ).one()

    # Pourcentage de victoire (calculé en Python)
    win_rate = (total_wins / total_games * 100) if total_games > 0 else 0.0

    # jointure pour calculer les lancers et la moyenne (PPD)

    stats_lancers = session.exec(
        select(
            func.count(Throw.calculated_score), # Nombre de lancers
            func.avg(Throw.calculated_score)    # Moyenne des points par lancer
        )
        .join(GameParticipation, 
              (Throw.game_id == GameParticipation.game_id) & 
              (Throw.player_username == GameParticipation.player_username))
        .where(GameParticipation.player_username == current_user.username)
        .where(GameParticipation.status == ValidationStatus.validated)
    ).first()

    # On récupère les résultats renvoyés par la base de données (sécurité si c'est vide)
    total_throws = stats_lancers[0] if stats_lancers and stats_lancers[0] else 0
    average_ppd = stats_lancers[1] if stats_lancers and stats_lancers[1] else 0.0

    # On groupe par points calculés (20, 19, etc.), on compte, et on prend le 1er (le point le plus touche)
    favorite_target_row = session.exec(
        select(Throw.calculated_score, func.count(Throw.id).label("hits"))
        .join(GameParticipation, 
              (Throw.game_id == GameParticipation.game_id) & 
              (Throw.player_username == GameParticipation.player_username))
        .where(GameParticipation.player_username == current_user.username)
        .where(GameParticipation.status == ValidationStatus.validated)
        .where(Throw.calculated_score > 0) # On ignore les ratés pour la zone favorite
        .group_by(Throw.calculated_score)
        .order_by(desc("hits"))
    ).first()
    
    favorite_target = favorite_target_row[0] if favorite_target_row else None

    # rates
    total_misses = session.exec(
        select(func.count(Throw.id))
        .join(GameParticipation, 
              (Throw.game_id == GameParticipation.game_id) & 
              (Throw.player_username == GameParticipation.player_username))
        .where(GameParticipation.player_username == current_user.username)
        .where(GameParticipation.status == ValidationStatus.validated)
        .where(Throw.calculated_score == 0) # La fléchette n'a rien touché
    ).one()

    #T20
    total_triple_20 = session.exec(
        select(func.count(Throw.id))
        .join(GameParticipation, 
              (Throw.game_id == GameParticipation.game_id) & 
              (Throw.player_username == GameParticipation.player_username))
        .where(GameParticipation.player_username == current_user.username)
        .where(GameParticipation.status == ValidationStatus.validated)
        .where(Throw.calculated_score == 20)
        .where(Throw.multiplier == 3) # (Score de 20 x 3 = 60)
    ).one()
    
    
    # Calcul des scores par TOUR (Tour complet de 3 fléchettes)
    scores_par_tour = session.exec(
        select(
            Throw.game_id, 
            Throw.tour_number, 
            func.sum(Throw.calculated_score * Throw.multiplier).label("tour_score")
        )
        .join(GameParticipation, 
              (Throw.game_id == GameParticipation.game_id) & 
              (Throw.player_username == GameParticipation.player_username))
        .where(GameParticipation.player_username == current_user.username)
        .where(GameParticipation.status == ValidationStatus.validated)
        .group_by(Throw.game_id, Throw.tour_number)
    ).all()

    total_180s = sum(1 for tour in scores_par_tour if tour.tour_score == 180)
    total_100_plus = sum(1 for tour in scores_par_tour if tour.tour_score >= 100 and tour.tour_score < 180)
    
    # groupe par points, on compte, et on prend le plus petit nombre de touché (-zone la moins touchee)
    #attention que ca prendra la zone la moins touchee mais pas celle jamais touchee (si par ex
    # il n'a jamais touche le 2 ca n'affichera pas 2 mais la zone qu'il a touche le moins parmi celles qu'il a touche)
    cursed_target_row = session.exec(
        select(Throw.calculated_score, func.count(Throw.id).label("hits"))
        .join(GameParticipation, 
              (Throw.game_id == GameParticipation.game_id) & 
              (Throw.player_username == GameParticipation.player_username))
        .where(GameParticipation.player_username == current_user.username)
        .where(GameParticipation.status == ValidationStatus.validated)
        .where(Throw.calculated_score > 0) # ignore les "0" (les ratés complets)
        .group_by(Throw.calculated_score)
        .order_by(func.count(Throw.id).asc())
    ).first()
    
    cursed_target = cursed_target_row[0] if cursed_target_row else None    
    
    return PlayerStats(
        total_games_played=total_games,
        total_wins=total_wins,
        win_rate_percentage=round(win_rate, 1),
        average_points_per_dart=round(average_ppd, 2),
        total_darts_thrown=total_throws,
        favorite_target=favorite_target,
        cursed_target=cursed_target,
        total_misses=total_misses,
        total_triple_20=total_triple_20,
        total_180s=total_180s,
        total_100_plus=total_100_plus        
    )
    
    

from pydantic import BaseModel
class Coordinate(BaseModel):
    x: float
    y: float

# Route dédiée à la Heatmap (renvoie juste les X et Y des 500 derniers lancers)
@router.get("/me/heatmap", response_model=List[Coordinate])
def get_my_heatmap(
    session: Session = Depends(get_session),
    current_user: Player = Depends(get_current_user)):
    
    # recup les X et Y des parties validées (limité aux 500 derniers pour pas faire exploser)
    coords = session.exec(
        select(Throw.x_position, Throw.y_position)
        .join(GameParticipation, 
              (Throw.game_id == GameParticipation.game_id) & 
              (Throw.player_username == GameParticipation.player_username))
        .where(GameParticipation.player_username == current_user.username)
        .where(GameParticipation.status == ValidationStatus.validated)
        .order_by(Throw.id.desc())
        .limit(500)
    ).all()

    # pour le front
    return [{"x": c[0], "y": c[1]} for c in coords]



    
from typing import Optional
from app.models.player import Friendship
#route pour filtrer ses amis (basé sur les lettres dans le pseudo) -> protégé (c'est pour son profil perso)
@router.get("/me/friends", response_model=List[PlayerPublic]) 
def get_my_friends(
    search: Optional[str] = Query(None, description="Taper quelques lettres pour chercher un ami"),
    session: Session = Depends(get_session),
    current_user: Player = Depends(get_current_user)):
    
    # chercher toutes les relations d'amitié qui impliquent le joueur actuel

    statement = select(Friendship).where(
        ((Friendship.user_username == current_user.username) | 
         (Friendship.friend_username == current_user.username)) &
        (Friendship.status == FriendshipStatus.accepted) 
    )
    
    friendships = session.exec(statement).all()

    # extrait juste les pseudos des amis dans une liste
    friend_usernames = []
    for f in friendships:
        if f.user_username == current_user.username:
            friend_usernames.append(f.friend_username)
        else:
            friend_usernames.append(f.user_username)

    if not friend_usernames:
        return [] # pas d'amis

    #récup les vrais profils des amis depuis la table Player
    query = select(Player).where(Player.username.in_(friend_usernames))


    if search:
        # Si le front envoie "?search=ad", on cherche "%ad%" (ce qui contient "ad")
        query = query.where(Player.username.ilike(f"%{search}%"))

    friends = session.exec(query).all()
    
    return friends


from app.models.player import FriendshipStatus
#route pour demander a ajouter un ami -> protégé (c'est pour son profil perso)
@router.post("/me/friends/request/{friend_username}")
def send_friend_request(
    friend_username: str,
    session: Session = Depends(get_session),
    current_user: Player = Depends(get_current_user)):
    
    if current_user.username == friend_username:
        raise HTTPException(status_code=400, detail="Vous ne pouvez pas vous ajouter vous-même !")

    friend = session.get(Player, friend_username)
    if not friend:
        raise HTTPException(status_code=404, detail=f"Le joueur '{friend_username}' n'existe pas.")

    # Vérifier s'il y a DEJA une relation (peu importe le sens)
    existing_friendship = session.exec(
        select(Friendship).where(
            ((Friendship.user_username == current_user.username) & (Friendship.friend_username == friend_username)) |
            ((Friendship.user_username == friend_username) & (Friendship.friend_username == current_user.username)))).first()

    if existing_friendship:
        if existing_friendship.status == FriendshipStatus.accepted:
            raise HTTPException(status_code=400, detail="Vous êtes déjà amis !")
        
        elif existing_friendship.status == FriendshipStatus.pending:
            raise HTTPException(status_code=400, detail="Une demande est déjà en attente entre vous deux.")
            
        elif existing_friendship.status == FriendshipStatus.rejected:
            # Si c'était refusé avant, on nettoie la db 
            session.delete(existing_friendship)
            session.commit()
            
            
    # On crée la demande en statut "pending"
    new_request = Friendship(
        user_username=current_user.username,
        friend_username=friend_username,
        status=FriendshipStatus.pending 
    )
    session.add(new_request)
    session.commit()
    
    return {"message": f"Demande d'ami envoyée à {friend_username} !"}


#route pour accepter ou refuser une demande d'ami -> protégé (c'est pour son profil perso)
@router.post("/me/friends/accept/{requester_username}")
def accept_friend_request(
    requester_username: str,
    session: Session = Depends(get_session),
    current_user: Player = Depends(get_current_user)):
    
    # On cherche la demande OÙ je suis le receveur (friend_username) 
    # ET le demandeur est requester_username
    friend_request = session.exec(
        select(Friendship).where(
            (Friendship.user_username == requester_username) &
            (Friendship.friend_username == current_user.username) &
            (Friendship.status == FriendshipStatus.pending))).first()

    if not friend_request:
        raise HTTPException(status_code=404, detail="Aucune demande d'ami en attente de ce joueur.")

    # changement du stattu
    friend_request.status = FriendshipStatus.accepted
    session.add(friend_request)
    session.commit()

    return {"message": f"Vous êtes maintenant ami avec {requester_username} !"}


#route pour rejeter ami
@router.post("/me/friends/reject/{requester_username}")
def reject_friend_request(
    requester_username: str,
    session: Session = Depends(get_session),
    current_user: Player = Depends(get_current_user)):
    
    # On cherche la demande en attente
    friend_request = session.exec(
        select(Friendship).where(
            (Friendship.user_username == requester_username) &
            (Friendship.friend_username == current_user.username) &
            (Friendship.status == FriendshipStatus.pending)
        )
    ).first()

    if not friend_request:
        raise HTTPException(status_code=404, detail="Aucune demande d'ami en attente de ce joueur.")

    # passe le statut en rejected
    friend_request.status = FriendshipStatus.rejected
    session.add(friend_request)
    session.commit()

    return {"message": f"Vous avez refusé la demande d'ami de {requester_username}."}



#route pour lister toutes les demandes d'amis
@router.get("/me/friends/requests", response_model=List[PlayerPublic])
def get_friend_requests(
    session: Session = Depends(get_session),
    current_user: Player = Depends(get_current_user)):
    
    # cherche toutes les requêtes en attente 
    statement = select(Friendship).where(
        (Friendship.friend_username == current_user.username) &
        (Friendship.status == FriendshipStatus.pending))
    
    pending_requests = session.exec(statement).all()

    if not pending_requests:
        return []

    # liste de ppseudo qui ont demandé l'amitié
    requester_usernames = [req.user_username for req in pending_requests]

    # chercher les profils complets de ces joueurs dans la base de données
    requesters = session.exec(select(Player).where(Player.username.in_(requester_usernames))).all()

    return requesters




# import random
# from pydantic import BaseModel

# # Le modèle que le Front envoie (juste le prénom tapé sur l'écran pour l'invité qui n'a pas de compte)
# class GuestCreate(BaseModel):
#     name: str 

# #route pour créer un compte invité (sans email ni mot de passe) -> pas besoin de token, n'importe qui devant la borne peut le faire
# @router.post("/guest", response_model=PlayerPublic)
# def create_guest_account(
#     guest_in: GuestCreate, 
#     session: Session = Depends(get_session)):
    
#     # Générer un username unique pour cet invité
#     while True:
#         random_suffix = random.randint(10000, 99999)
#         guest_username = f"guest_{random_suffix}"
        
#         #verif si pseudo déjà pris
#         existing_user = session.get(Player, guest_username)
#         if not existing_user:
#             break

#     # creer le compte fantôme da,ns db
#     db_guest = Player(
#         username=guest_username,
#         name=guest_in.name,
#         is_guest=True, 
#         email=None,
#         hashed_password=None
#     )
    
#     session.add(db_guest)
#     session.commit()
#     session.refresh(db_guest)
    
#     logger.info(f"Compte invité créé : {guest_username} ({guest_in.name})")
    
#     return db_guest