from sqlmodel import Session, select, func

from datetime import datetime, timedelta, timezone

from app.models.game import Game, GameStatus
from app.models.target import Target
from app.models.throw import Throw
from app.utils.darts_logic import get_checkout_suggestion


# Construit l'état complet de la partie (scores, moyennes, historique).
# Cette fonction est universelle et ne dépend pas de l'utilisateur qui regarde la partie
def build_base_game_state(game_id: int, session: Session) -> dict:
    
    game = session.get(Game, game_id)
    if not game:
        return None

    game_dict = game.model_dump()

    #Infos de la cible
    target = session.get(Target, game.target_id)
    if target:
        game_dict["target_name"] = target.name
        game_dict["target_location"] = target.location
    else:
        game_dict["target_name"] = "Cible inconnue"
        game_dict["target_location"] = "Lieu inconnu"
        
    # trie les joueurs par date d'arrivée
    participants_chronologiques = sorted(game.participations, key=lambda p: p.join_date)

    # L'Hôte est tjs le premier joueur de cette liste triée 
    if participants_chronologiques:
        host_username = participants_chronologiques[0].player_username
    else:
        host_username = None

    participations_enrichies = []

    # On boucle sur la liste triee pour construire les données de chaque participant dans l'ordre d'arrivée (pour le front)
    for p in participants_chronologiques:
        p_dict = p.model_dump()
        p_dict["player_name"] = p.player.name if p.player else "Joueur inconnu"
        p_dict["is_host"] = (p.player_username == host_username)
        p_dict["is_friend"] = False
        
        # Calcul de la moyenne (PPD)
        darts_thrown = session.exec(
            select(func.count(Throw.id))
            .where(Throw.game_id == game.id)
            .where(Throw.player_username == p.player_username)
        ).one()

        if darts_thrown > 0:
            if game.mode in ["501", "301"]:
                starting_score = 501 if game.mode == "501" else 301
                points_scored = starting_score - p.current_score
                p_dict["current_average"] = round(points_scored / darts_thrown, 2)
            else: 
                p_dict["current_average"] = round(p.current_score / darts_thrown, 2)
        else:
            p_dict["current_average"] = 0.0

        # Fléchettes restantes & Suggestions
        if game.status == GameStatus.waiting:
            darts_left = 3
        else:
            darts_left = 4 - game.current_dart_number

        if game.mode in ["501", "301"]:
            p_dict["checkout_suggestion"] = get_checkout_suggestion(p.current_score, darts_left)
        else:
            p_dict["checkout_suggestion"] = []

        # HISTORIQUE : Les 3 dernières fléchettes du dernier tour joué
        last_turn = session.exec(
            select(func.max(Throw.tour_number))
            .where(Throw.game_id == game.id)
            .where(Throw.player_username == p.player_username)
        ).one_or_none()
        
        last_3_points = []
        if last_turn is not None:
            recent_throws = session.exec(
                select(Throw)
                .where(Throw.game_id == game.id)
                .where(Throw.player_username == p.player_username)
                .where(Throw.tour_number == last_turn)
                .order_by(Throw.dart_number)
            ).all()
            
            for t in recent_throws:
                last_3_points.append({
                    "points": t.calculated_score,
                    "multiplier": t.multiplier,
                    "total": t.calculated_score * t.multiplier
                })
                
        p_dict["last_3_points"] = last_3_points

        participations_enrichies.append(p_dict)

    game_dict["participations"] = participations_enrichies
    
    # coord brutes, pour anim de la cible sur interface
    all_throws = session.exec(
        select(Throw)
        .where(Throw.game_id == game.id)
    ).all()
    
    current_player_hits = []
    other_hits = []
    
    for t in all_throws:
        # On ignore les lancers manuels (qui n'ont pas de vraies coordonnées)
        # (Si x et y sont exactement 0.0, c'est un lancer manuel du téléphone)
        if t.x_position == 0.0 and t.y_position == 0.0:
            continue
            
        hit_data = {"x": t.x_position, "y": t.y_position}
        
        # sépare le joueur actuel des autres
        if t.player_username == game.current_player_username:
            current_player_hits.append(hit_data)
        else:
            other_hits.append(hit_data)
            
    game_dict["board_hits"] = {
        "current_player": current_player_hits,
        "others": other_hits
    }
    
    return game_dict



def cleanup_inactive_games(session: Session):
    
    # seuil de 20 minutes
    timeout_limit = datetime.now(timezone.utc) - timedelta(minutes=20)
    
    # cherche les parties "en attente" ou "en cours" qui n'ont pas bougé
    statement = (
        select(Game)
        .where(Game.status.in_([GameStatus.waiting, GameStatus.in_progress]))
        .where(Game.last_interaction < timeout_limit)
    )
    
    abandoned_games = session.exec(statement).all()

    # ferme une par une
    for game in abandoned_games:
        game.status = GameStatus.finished
        game.end_date = datetime.now(timezone.utc)
        session.add(game)
        
    if abandoned_games:
        session.commit()
        import logging
        logging.getLogger(__name__).info(f"[Nettoyage] {len(abandoned_games)} partie(s) abandonnée(s) ont été clôturées.")        

