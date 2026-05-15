# On importe tous nos modèles ici pour que SQLModel les connaisse tous (debug)
#Si on ne le fait pas, ca bug et ne cree pas toutes les tables d'un coup
from .player import Player
from .target import Target
from .game import Game
from .game_participation import GameParticipation
from .throw import Throw