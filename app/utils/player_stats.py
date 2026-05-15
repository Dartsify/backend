from datetime import datetime, timedelta, timezone
from typing import Optional
from sqlmodel import Session, select, func, desc
from app.models.game import Game
from app.models.game_participation import GameParticipation, ValidationStatus
from app.models.throw import Throw
from app.models.player import PlayerStats
from app.models.target import Target




def calculate_player_stats(username: str, session: Session, since_date: Optional[datetime]= None) -> PlayerStats:
    # Parties jouées
    q_games = select(func.count()).select_from(GameParticipation)
    if since_date:
        q_games = q_games.join(Game).where(Game.end_date >= since_date)
    total_games = session.exec(
        q_games.where(GameParticipation.player_username == username)
        .where(GameParticipation.status == ValidationStatus.validated)
    ).one()

    # Victoires
    q_wins = select(func.count()).select_from(GameParticipation)
    if since_date:
        q_wins = q_wins.join(Game).where(Game.end_date >= since_date)
    total_wins = session.exec(
        q_wins.where(GameParticipation.player_username == username)
        .where(GameParticipation.status == ValidationStatus.validated)
        .where(GameParticipation.position == 1)
    ).one()

    win_rate = (total_wins / total_games * 100) if total_games > 0 else 0.0

    # Lancers et Moyenne (PPD)
    q_lancers = (
        select(func.count(Throw.calculated_score), func.avg(Throw.calculated_score))
        .join(GameParticipation, (Throw.game_id == GameParticipation.game_id) & (Throw.player_username == GameParticipation.player_username))
    )
    if since_date:
        q_lancers = q_lancers.join(Game, Throw.game_id == Game.id).where(Game.end_date >= since_date)
    stats_lancers = session.exec(
        q_lancers.where(GameParticipation.player_username == username)
        .where(GameParticipation.status == ValidationStatus.validated)
    ).first()

    total_throws = stats_lancers[0] if stats_lancers and stats_lancers[0] else 0
    average_ppd = stats_lancers[1] if stats_lancers and stats_lancers[1] else 0.0

    # 3 Zones favorites (dans l'ordre) en tenant compte du multiplicateur
    q_fav = (
        select(Throw.calculated_score, Throw.multiplier, func.count(Throw.id).label("hits"))
        .join(GameParticipation, (Throw.game_id == GameParticipation.game_id) & (Throw.player_username == GameParticipation.player_username))
    )
    if since_date:
        q_fav = q_fav.join(Game, Throw.game_id == Game.id).where(Game.end_date >= since_date)
        
    favorite_targets_rows = session.exec(
        q_fav.where(GameParticipation.player_username == username)
        .where(GameParticipation.status == ValidationStatus.validated)
        .where(Throw.calculated_score > 0)
        .group_by(Throw.calculated_score, Throw.multiplier) 
        .order_by(desc("hits"))
        .limit(3)
    ).all()
    
    favorite_targets = []
    for row in favorite_targets_rows:
        score = row[0]
        mult = row[1]
        if score == 25:
            label = "Double Bullseye" if mult == 2 else "Bullseye"
        else:
            if mult == 3: label = f"T{score}"
            elif mult == 2: label = f"D{score}"
            else: label = f"{score}"
        favorite_targets.append(label)
    
    # Les ratés (0 points)
    q_miss = select(func.count(Throw.id)).join(GameParticipation, (Throw.game_id == GameParticipation.game_id) & (Throw.player_username == GameParticipation.player_username))
    if since_date:
        q_miss = q_miss.join(Game, Throw.game_id == Game.id).where(Game.end_date >= since_date)
    total_misses = session.exec(
        q_miss.where(GameParticipation.player_username == username)
        .where(GameParticipation.status == ValidationStatus.validated)
        .where(Throw.calculated_score == 0)
    ).one()

    # Triple 20
    q_t20 = select(func.count(Throw.id)).join(GameParticipation, (Throw.game_id == GameParticipation.game_id) & (Throw.player_username == GameParticipation.player_username))
    if since_date:
        q_t20 = q_t20.join(Game, Throw.game_id == Game.id).where(Game.end_date >= since_date)
    total_triple_20 = session.exec(
        q_t20.where(GameParticipation.player_username == username)
        .where(GameParticipation.status == ValidationStatus.validated)
        .where(Throw.calculated_score == 20)
        .where(Throw.multiplier == 3)
    ).one()

    # Scores par tour (180s et 100+)
    q_tours = select(
        Throw.game_id, Throw.tour_number, func.sum(Throw.calculated_score * Throw.multiplier).label("tour_score")
    ).join(GameParticipation, (Throw.game_id == GameParticipation.game_id) & (Throw.player_username == GameParticipation.player_username))
    if since_date:
        q_tours = q_tours.join(Game, Throw.game_id == Game.id).where(Game.end_date >= since_date)
        
    scores_par_tour = session.exec(
        q_tours.where(GameParticipation.player_username == username)
        .where(GameParticipation.status == ValidationStatus.validated)
        .group_by(Throw.game_id, Throw.tour_number)
    ).all()

    total_180s = sum(1 for tour in scores_par_tour if tour.tour_score == 180)
    total_100_plus = sum(1 for tour in scores_par_tour if tour.tour_score >= 100 and tour.tour_score < 180)

    # Zone maudite
    q_cursed = select(Throw.calculated_score, Throw.multiplier, func.count(Throw.id).label("hits")).join(GameParticipation, (Throw.game_id == GameParticipation.game_id) & (Throw.player_username == GameParticipation.player_username))
    if since_date:
        q_cursed = q_cursed.join(Game, Throw.game_id == Game.id).where(Game.end_date >= since_date)
    cursed_target_row = session.exec(
        q_cursed.where(GameParticipation.player_username == username)
        .where(GameParticipation.status == ValidationStatus.validated)
        .where(Throw.calculated_score > 0)
        .group_by(Throw.calculated_score, Throw.multiplier)
        .order_by(func.count(Throw.id).asc())
    ).first()
    
    cursed_target = None
    if cursed_target_row:
        score = cursed_target_row[0]
        mult = cursed_target_row[1]
        if score == 25:
            cursed_target = "Double Bullseye" if mult == 2 else "Bullseye"
        else:
            if mult == 3: cursed_target = f"T{score}"
            elif mult == 2: cursed_target = f"D{score}"
            else: cursed_target = f"{score}"

    # Cible préférée / Lieu le plus joué 
    q_location = (
        select(Target.name, Target.location, func.count(Game.id).label("games_count"))
        .join(Game, Game.target_id == Target.id)
        .join(GameParticipation, GameParticipation.game_id == Game.id)
    )
    if since_date:
        q_location = q_location.where(Game.end_date >= since_date)
        
    favorite_location_row = session.exec(
        q_location.where(GameParticipation.player_username == username)
        .where(GameParticipation.status == ValidationStatus.validated)
        .group_by(Target.name, Target.location)
        .order_by(desc("games_count"))
    ).first()
    
    favorite_play_location = None
    if favorite_location_row:
        nom_cible = favorite_location_row[0]
        ville_cible = favorite_location_row[1]
        favorite_play_location = f"{nom_cible} ({ville_cible})"
            
    return PlayerStats(
        total_games_played=total_games,
        total_wins=total_wins,
        win_rate_percentage=round(win_rate, 1),
        average_points_per_dart=round(average_ppd, 2),
        total_darts_thrown=total_throws,
        favorite_targets=favorite_targets,
        cursed_target=cursed_target,
        total_misses=total_misses,
        total_triple_20=total_triple_20,
        total_180s=total_180s,
        total_100_plus=total_100_plus,
        favorite_play_location=favorite_play_location 
    )