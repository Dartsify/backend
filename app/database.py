from sqlmodel import SQLModel, create_engine, Session, select
from fastapi import Depends
from typing import Annotated

from datetime import datetime, timedelta, timezone
import random

from app.models.target import Target

#pour creation de l'admin
from app.config import ADMIN_NAME, ADMIN_USERNAME, ADMIN_PASSWORD, ADMIN_EMAIL

#Cree la connexion à la base de données SQLite (fichier database.db)
sqlite_file_name = "database.db"
sqlite_url = f"sqlite:///{sqlite_file_name}"

connect_args = {"check_same_thread": False}# accorde fastapi à utiliser la même connexion à la base de données dans différents threads (utile pour les requêtes simultanées)
engine = create_engine(sqlite_url, connect_args=connect_args)

#Ceeration de la base de données et des tables à partir des modèles SQLModel définis dans app/models
def create_db_and_tables():
    SQLModel.metadata.create_all(engine)

# Cree la session -> session est ce qui stocke les objets en mémoire et garde une trace de tous les changements 
# (puis utilise le moteur pour communiquer avec la base de données et enregistrer les changements)
def get_session():
    with Session(engine) as session:
        yield session


SessionDep = Annotated[Session, Depends(get_session)]

#Creation de l'admin initial
def create_initial_admin():
    # importe les modèles et la sécurité ici pour éviter les erreurs "d'import circulaire" au démarrage (debug)
    from app.models.player import Player
    from app.security.auth import hash_password

    with Session(engine) as session:
        # vérif si admin existe déjà
        admin_user = session.exec(select(Player).where(Player.username == ADMIN_USERNAME)).first()
        
        if not admin_user:
            # Si existe pas, on hache son mot de passe et on le crée
            hashed_pw = hash_password(ADMIN_PASSWORD)
            new_admin = Player(
                username=ADMIN_USERNAME,
                email=ADMIN_EMAIL,
                name=ADMIN_NAME,
                hashed_password=hashed_pw,
                is_admin=True  # badge admin
            )
            session.add(new_admin)
            session.commit()


#creation de données de test pour le développement (cibles et joueurs)
def seed_test_data():
    from app.security.auth import hash_password
    from app.models.player import Player

    with Session(engine) as session:

        # cibles
        cibles_test = [
            {"id": "000001", "name": "Cible Test 1", "location": "Bar Salle 1"},
            {"id": "000002", "name": "Cible Test 2", "location": "Bar Salle 2"},
            {"id": "190256", "name": "Cible Dartsify", "location": "Faculté Polytechnique de Mons"}
        ]

        for cible_data in cibles_test:
            if not session.get(Target, cible_data["id"]):
                new_target = Target(
                    id=cible_data["id"],
                    name=cible_data["name"],
                    location=cible_data["location"]
                )
                session.add(new_target)

        # joueurs
        # On leur met un mot de passe facile et connu pour que Mathias puisse se connecter
        mot_de_passe_test = hash_password("Test123") 

        joueurs_test = [
            {"username": "math", "email": "mathias@test.com", "name": "Mathias"},
            {"username": "adri", "email": "adri@test.com", "name": "Adrien"},
            {"username": "alex", "email": "alex@test.com", "name": "Alexandre"}
        ]

        for joueur_data in joueurs_test:
            if not session.get(Player, joueur_data["username"]):
                new_player = Player(
                    username=joueur_data["username"],
                    email=joueur_data["email"],
                    name=joueur_data["name"],
                    hashed_password=mot_de_passe_test
                )
                session.add(new_player)

        session.commit()
        
        


def seed_random_games_and_throws():
    # Imports locaux pour éviter les imports circulaires
    from app.models.game import Game, GameStatus, GameModeAllowed
    from app.models.game_participation import GameParticipation, ValidationStatus
    from app.models.throw import Throw
    from app.models.player import Player
    from app.models.target import Target

    with Session(engine) as session:
        # On vérifie si des parties existent déjà (pour éviter de générer 1000 parties à chaque redémarrage)
        existing_games = session.exec(select(Game)).first()
        if existing_games:
            return  # On quitte la fonction, la DB est déjà remplie 

        print("Création de parties et de lancers aléatoires pour les tests de Mathias...")

        # 2. Récupérer les joueurs et les cibles existants
        players = session.exec(select(Player).where(Player.username.in_(["math", "adri", "alex"]))).all()
        targets = session.exec(select(Target)).all()

        if not players or not targets:
            print("Erreur : Joueurs ou cibles de test introuvables. Lance seed_test_data() d'abord.")
            return

        # Créer 5 parties terminées dans le passé (entre il y a 1 et 30 jours)
        for game_idx in range(5):
            target = random.choice(targets)
            date_partie = datetime.now(timezone.utc) - timedelta(days=random.randint(1, 30))

            new_game = Game(
                mode=GameModeAllowed.mode_501,
                creation_date=date_partie,
                start_date=date_partie + timedelta(minutes=1),
                end_date=date_partie + timedelta(minutes=15),
                status=GameStatus.finished,
                target_id=target.id,
                current_turn_number=6,
                current_dart_number=3
            )
            session.add(new_game)
            session.commit()  # On commit pour générer l'ID de la partie

            # On prend 2 ou 3 joueurs au hasard pour cette partie
            part_players = random.sample(players, k=random.randint(2, 3))

            # Ajouter les joueurs à la partie
            for idx, player in enumerate(part_players):
                is_winner = (idx == 0)  # Le premier tiré au sort gagne la partie
                
                participation = GameParticipation(
                    game_id=new_game.id,
                    player_username=player.username,
                    current_score=0 if is_winner else random.randint(2, 150),
                    final_score=0 if is_winner else random.randint(2, 150),
                    position=1 if is_winner else idx + 1,
                    status=ValidationStatus.validated, 
                    join_date=date_partie
                )
                session.add(participation)

                # Générer 15 lancers (5 tours) pour chaque joueur
                tour = 1
                for dart_idx in range(15):
                    dart_num = (dart_idx % 3) + 1
                    
                    # (Beaucoup de 20 et de 19, un peu de 1 et 5 à côté, quelques Bull)
                    scores_possibles = [
                        20, 19, 18, 17, 16, 15, # Les cibles favorites (Très fréquent)
                        1, 5, 7, 3, 2,          # Les voisins des favorites (Erreurs fréquentes)
                        14, 13, 12, 11, 10,     # Le milieu du tableau (Occasionnel)
                        9, 8, 6, 4,             # Les petits nombres (Rare)
                        25, 0                   # Bullseye et Hors Cible
                    ]
                    
                    poids_probabilites = [
                        25, 15, 10, 8, 8, 6,    # Très lourd pour le 20 et le 19
                        5, 5, 4, 4, 3,          # Poids moyen pour les erreurs de tir
                        2, 2, 2, 2, 2,          # Faible chance
                        1, 1, 1, 1,             # Très faible chance
                        4, 3                    # Un peu de Bull et quelques Miss
                    ]
                    
                    score = random.choices(scores_possibles, weights=poids_probabilites)[0]
                    
                    if score == 0:
                        mult = 1
                    elif score == 25:
                        mult = random.choice([1, 2])
                    else:
                        mult = random.choices([1, 2, 3], weights=[70, 15, 15])[0] # 15% de chance de Double ou Triple

                    throw = Throw(
                        game_id=new_game.id,
                        player_username=player.username,
                        tour_number=tour,
                        dart_number=dart_num,
                        time_throw=date_partie + timedelta(minutes=tour),
                        x_position=random.uniform(200.0, 800.0), # Coordonnées au pif pour l'animation
                        y_position=random.uniform(200.0, 800.0),
                        camera_id=random.choice([1, 2, 3]),
                        calculated_score=score,
                        multiplier=mult
                    )
                    session.add(throw)
                    
                    if dart_num == 3:
                        tour += 1

        session.commit()
        print("5 Parties et des centaines de fléchettes générées avec succès !")


