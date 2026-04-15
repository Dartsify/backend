import logging
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from sqlmodel import Session, select, func, desc
from app.database import get_session

from app.models.player import Player, PlayerCreate, PlayerRead, PlayerUpdate, PlayerPublic, PlayerStats, PasswordUpdate, Friendship, FriendshipStatus, HitData, ZoneStatsResponse
from app.models.player import FriendRequestResponse, FriendResponse, PlayerProfile
from app.models.game import Game, GameStatus
from app.models.game_participation import GameParticipation, ValidationStatus
from app.models.throw import Throw

from app.security.auth import hash_password, verify_password, get_current_user


#config du router et du logger
router = APIRouter(prefix="/players", tags=["players"]) #creation route
logger = logging.getLogger(__name__) # Récupère le logger configuré



def calculate_player_stats(username: str, session: Session) -> PlayerStats:
# Parties jouées
    total_games = session.exec(
        select(func.count())
        .select_from(GameParticipation)
        .where(GameParticipation.player_username == username)
        .where(GameParticipation.status == ValidationStatus.validated)
    ).one()

    # Victoires
    total_wins = session.exec(
        select(func.count())
        .select_from(GameParticipation)
        .where(GameParticipation.player_username == username)
        .where(GameParticipation.status == ValidationStatus.validated)
        .where(GameParticipation.position == 1)
    ).one()

    win_rate = (total_wins / total_games * 100) if total_games > 0 else 0.0

    # Lancers et Moyenne (PPD)
    stats_lancers = session.exec(
        select(
            func.count(Throw.calculated_score),
            func.avg(Throw.calculated_score)
        )
        .join(GameParticipation, 
              (Throw.game_id == GameParticipation.game_id) & 
              (Throw.player_username == GameParticipation.player_username))
        .where(GameParticipation.player_username == username)
        .where(GameParticipation.status == ValidationStatus.validated)
    ).first()

    total_throws = stats_lancers[0] if stats_lancers and stats_lancers[0] else 0
    average_ppd = stats_lancers[1] if stats_lancers and stats_lancers[1] else 0.0

    # 3 Zones favorites (dans l'ordre) en tenant compte du multiplicateur
    favorite_targets_rows = session.exec(
        select(Throw.calculated_score, Throw.multiplier, func.count(Throw.id).label("hits"))
        .join(GameParticipation, 
              (Throw.game_id == GameParticipation.game_id) & 
              (Throw.player_username == GameParticipation.player_username))
        .where(GameParticipation.player_username == username)
        .where(GameParticipation.status == ValidationStatus.validated)
        .where(Throw.calculated_score > 0)
        .group_by(Throw.calculated_score, Throw.multiplier) 
        .order_by(desc("hits"))
        .limit(3)
    ).all()

    # On transforme ça en labels pour Mathias (ex: ["T20", "D16", "20"])
    favorite_targets = []
    for row in favorite_targets_rows:
        score = row[0]
        mult = row[1]
        
        if score == 25:
            label = "Double Bullseye" if mult == 2 else "Bullseye"
        else:
            if mult == 3:
                label = f"T{score}"
            elif mult == 2:
                label = f"D{score}"
            else:
                label = f"{score}" # Simple
                
        favorite_targets.append(label)
    
    # Les ratés (0 points)
    total_misses = session.exec(
        select(func.count(Throw.id))
        .join(GameParticipation, 
              (Throw.game_id == GameParticipation.game_id) & 
              (Throw.player_username == GameParticipation.player_username))
        .where(GameParticipation.player_username == username)
        .where(GameParticipation.status == ValidationStatus.validated)
        .where(Throw.calculated_score == 0)
    ).one()

    # Triple 20
    total_triple_20 = session.exec(
        select(func.count(Throw.id))
        .join(GameParticipation, 
              (Throw.game_id == GameParticipation.game_id) & 
              (Throw.player_username == GameParticipation.player_username))
        .where(GameParticipation.player_username == username)
        .where(GameParticipation.status == ValidationStatus.validated)
        .where(Throw.calculated_score == 20)
        .where(Throw.multiplier == 3)
    ).one()

    # Scores par tour (180s et 100+)
    scores_par_tour = session.exec(
        select(
            Throw.game_id, 
            Throw.tour_number, 
            func.sum(Throw.calculated_score * Throw.multiplier).label("tour_score")
        )
        .join(GameParticipation, 
              (Throw.game_id == GameParticipation.game_id) & 
              (Throw.player_username == GameParticipation.player_username))
        .where(GameParticipation.player_username == username)
        .where(GameParticipation.status == ValidationStatus.validated)
        .group_by(Throw.game_id, Throw.tour_number)
    ).all()

    total_180s = sum(1 for tour in scores_par_tour if tour.tour_score == 180)
    total_100_plus = sum(1 for tour in scores_par_tour if tour.tour_score >= 100 and tour.tour_score < 180)

    # Zone maudite
    cursed_target_row = session.exec(
        select(Throw.calculated_score, Throw.multiplier, func.count(Throw.id).label("hits"))
        .join(GameParticipation, 
              (Throw.game_id == GameParticipation.game_id) & 
              (Throw.player_username == GameParticipation.player_username))
        .where(GameParticipation.player_username == username)
        .where(GameParticipation.status == ValidationStatus.validated)
        .where(Throw.calculated_score > 0)
        .group_by(Throw.calculated_score, Throw.multiplier) # <-- On groupe par les DEUX !
        .order_by(func.count(Throw.id).asc())
    ).first()
    
    cursed_target = None
    if cursed_target_row:
        score = cursed_target_row[0]
        mult = cursed_target_row[1]
        if score == 25:
            cursed_target = "Double Bullseye" if mult == 2 else "Bullseye"
        else:
            if mult == 3:
                cursed_target = f"T{score}"
            elif mult == 2:
                cursed_target = f"D{score}"
            else:
                cursed_target = f"{score}"
            
    
    # On retourne directement l'objet Pydantic rempli avec toutes les stats calculées
    return PlayerStats(
        total_games_played=total_games,
        total_wins=total_wins,
        win_rate_percentage=round(win_rate, 1),
        average_points_per_dart=round(average_ppd, 2),
        total_darts_thrown=total_throws,
        favorite_target=favorite_targets,
        cursed_target=cursed_target,
        total_misses=total_misses,
        total_triple_20=total_triple_20,
        total_180s=total_180s,
        total_100_plus=total_100_plus        
    )




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




# #Lire un player spécifique basé sur son username -> admin ou ami ou lui meme
@router.get("/{username}", response_model=PlayerProfile)
def read_player(username: str,
                session: Session = Depends(get_session),
                current_user: Player = Depends(get_current_user)):
    
    # Chercher le joueur
    player = session.get(Player, username)
    if not player:
        raise HTTPException(status_code=404, detail=f"Le joueur '{username}' n'existe pas.")

    #Vérif les droits (Admin, Soi-même ou Ami)
    is_me = (current_user.username == username)
    is_admin = current_user.is_admin
    
    is_friend = session.exec(
        select(Friendship).where(
            (
                ((Friendship.user_username == current_user.username) & (Friendship.friend_username == username)) |
                ((Friendship.user_username == username) & (Friendship.friend_username == current_user.username))
            ) &
            (Friendship.status == FriendshipStatus.accepted)
        )
    ).first()

    if not (is_admin or is_me or is_friend):
        raise HTTPException(status_code=403, detail="Accès refusé. Vous devez être ami pour voir ce profil.")

    # Calculer les stats du joueur
    player_stats = calculate_player_stats(username, session) 

    # transforme l'objet DB en dictionnaire pour manipuler les champs
    profile_data = player.model_dump()
    profile_data["stats"] = player_stats

    # secu : On retire l'email si ce n'est pas l'admin ou soi-même
    if not (is_admin or is_me):
        profile_data["email"] = None 

    return profile_data




#Route pour avoir les stats perso du joueur
@router.get("/me/stats", response_model=PlayerStats)
def get_my_stats(
    session: Session = Depends(get_session),
    current_user: Player = Depends(get_current_user)):
    
    return calculate_player_stats(current_user.username, session)
    
    
    

# Récupère la distribution complète de toutes les fléchettes lancées par le joueur
# -> pour générer un graphique en bâtons côté Front-end
@router.get("/me/zones_stats", response_model=ZoneStatsResponse)
def get_my_zones_stats(
    session: Session = Depends(get_session),
    current_user: Player = Depends(get_current_user)):
    
    # groupe par score ET par multiplicateur
    hit_distribution_rows = session.exec(
        select(Throw.calculated_score, Throw.multiplier, func.count(Throw.id).label("hits"))
        .join(GameParticipation, 
              (Throw.game_id == GameParticipation.game_id) & 
              (Throw.player_username == GameParticipation.player_username))
        .where(GameParticipation.player_username == current_user.username) # filtre ce joueur
        .where(GameParticipation.status == ValidationStatus.validated)     # Uniquement les parties validées
        .group_by(Throw.calculated_score, Throw.multiplier)
        .order_by(desc("hits")) # Trie de la zone la plus touchée à la moins touchée
    ).all()

    hit_distribution = []
    
    for row in hit_distribution_rows:
        score = row[0]
        mult = row[1]
        hits = row[2]

        if score == 0:
            label = "Miss"
        elif score == 25:
            label = "Double Bullseye" if mult == 2 else "Bullseye"
        else:
            if mult == 3:
                label = f"T{score}"
            elif mult == 2:
                label = f"D{score}"
            else:
                label = f"{score}"

        hit_distribution.append(HitData(zone=label, hits=hits))

    return ZoneStatsResponse(hit_distribution=hit_distribution)




#modele pour la heatmap (coordonnées X et Y des lancers)
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


    

#route pour filtrer ses amis (basé sur les lettres dans le pseudo) -> protégé (c'est pour son profil perso)
@router.get("/me/friends", response_model=List[FriendResponse]) 
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

    # extrait juste les pseudos des amis dans une liste et leur date dans un dict
    friend_usernames = []
    friend_dates = {}
    
    for f in friendships:
        if f.user_username == current_user.username:
            ami = f.friend_username
        else:
            ami = f.user_username
            
        friend_usernames.append(ami)
        friend_dates[ami] = f.created_at # On sauvegarde la date de cette amitié

    if not friend_usernames:
        return [] # pas d'amis

    #récup les vrais profils des amis depuis la table Player
    query = select(Player).where(Player.username.in_(friend_usernames))

    if search:
        # Si le front envoie "?search=ad", on cherche "%ad%" (ce qui contient "ad")
        query = query.where(Player.username.ilike(f"%{search}%"))

    friends = session.exec(query).all()
    
    #recup de plus de infos pour front
    my_game_ids_query = select(GameParticipation.game_id).where(GameParticipation.player_username == current_user.username)
    
    enriched_friends = []
    
    for friend in friends:
        friend_dict = friend.model_dump()
        
        #prendre date exacte dans le dict de chaque ami pour le front
        friend_dict["friends_since"] = friend_dates[friend.username] 
        
        # Nombre de parties finies jouées ENSEMBLE
        # C'est-à-dire : l'ami est dans une partie dont l'ID fait partie de mes parties
        games_together_ids = session.exec(
            select(GameParticipation.game_id)
            .join(Game)
            .where(GameParticipation.player_username == friend.username)
            .where(GameParticipation.game_id.in_(my_game_ids_query))
            .where(Game.status == GameStatus.finished) # On ne compte que les parties terminées
        ).all()
        
        friend_dict["games_played_together"] = len(games_together_ids)
        
        # Nombre de victoires de current_user contre cet ami
        games_won = 0
        if games_together_ids:
            games_won = session.exec(
                select(func.count())
                .select_from(GameParticipation)
                .where(GameParticipation.player_username == current_user.username)
                .where(GameParticipation.game_id.in_(games_together_ids))
                .where(GameParticipation.position == 1) # position 1 = Victoire 
            ).one()
            
        friend_dict["games_won_against"] = games_won
        
        enriched_friends.append(friend_dict)

    return enriched_friends




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
@router.get("/me/friends/requests", response_model=List[FriendRequestResponse])
def get_friend_requests(
    session: Session = Depends(get_session),
    current_user: Player = Depends(get_current_user)):
    
    # Cherche toutes les requetes en attente 
    statement = select(Friendship).where(
        (Friendship.friend_username == current_user.username) &
        (Friendship.status == FriendshipStatus.pending))
    
    pending_requests = session.exec(statement).all()

    if not pending_requests:
        return []

    # dictionnaire pour lier chaque pseudo à sa date de demande
    # Ex: {"bobby": "2026-04-01...", "roger": "2026-04-02..."}
    request_dates = {req.user_username: req.created_at for req in pending_requests}

    requesters = session.exec(select(Player).where(Player.username.in_(request_dates.keys()))).all()

    enriched_requests = []
    
    for requester in requesters:
        # Transforme le profil db en dictionnaire
        req_dict = requester.model_dump()
        
        # ajout de la date de demande correspondante 
        req_dict["request_date"] = request_dates[requester.username]
        
        enriched_requests.append(req_dict)

    return enriched_requests




#route pour supprimer un ami (effacement mutuel)
@router.delete("/me/friends/{friend_username}")
def remove_friend(
    friend_username: str,
    session: Session = Depends(get_session),
    current_user: Player = Depends(get_current_user)):
    
    # On cherche la relation d'amitié peu importe qui a fait la demande au départ
    friendship = session.exec(
        select(Friendship).where(
            ((Friendship.user_username == current_user.username) & (Friendship.friend_username == friend_username)) |
            ((Friendship.user_username == friend_username) & (Friendship.friend_username == current_user.username))
        )
    ).first()
    
    if not friendship:
        raise HTTPException(status_code=404, detail="Vous n'êtes pas/plus amis avec ce joueur.")
        
    session.delete(friendship)
    session.commit()
    
    logger.info(f"{current_user.username} a supprimé {friend_username} de ses amis.")
    
    return {"message": f"Vous n'êtes plus amis avec {friend_username}."}




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