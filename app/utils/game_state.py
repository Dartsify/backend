from sqlmodel import Session, select, func
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

    # Hôte de la partie
    host_username = game.current_player_username if game.status == GameStatus.waiting else game.participations[0].player_username

    participations_enrichies = []

    for p in game.participations:
        p_dict = p.model_dump()
        p_dict["player_name"] = p.player.name if p.player else "Joueur inconnu"
        p_dict["is_host"] = (p.player_username == host_username)
        p_dict["is_friend"] = False # Par défaut, sera écrasé par la route GET personnalisée

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
    return game_dict