import asyncio
from typing import Dict, List

class GameStreamManager:
    def __init__(self):
        # Un dictionnaire qui associe un ID de partie à une liste de "boîtes aux lettres" (files d'attente)
        self.listeners: Dict[int, List[asyncio.Queue]] = {}

    def add_listener(self, game_id: int) -> asyncio.Queue:
        if game_id not in self.listeners:
            self.listeners[game_id] = []
        q = asyncio.Queue()
        self.listeners[game_id].append(q)
        return q

    def remove_listener(self, game_id: int, q: asyncio.Queue):
        if game_id in self.listeners and q in self.listeners[game_id]:
            self.listeners[game_id].remove(q)
            #si plus personne n'écoute cette partie, on nettoie
            if not self.listeners[game_id]:
                del self.listeners[game_id]

    async def broadcast(self, game_id: int, message: str):
        # S'il y a des téléphones qui écoutent cette partie, on glisse le message dans leur boîte
        if game_id in self.listeners:
            for q in self.listeners[game_id]:
                await q.put(message)

# On crée notre facteur unique pour toute l'application
stream_manager = GameStreamManager()