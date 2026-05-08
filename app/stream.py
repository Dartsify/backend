import asyncio
from typing import Dict, List

import json
from sqlmodel import Session
from app.utils.game_state import build_base_game_state

from fastapi.encoders import jsonable_encoder

#via la doc SSE 
class GameStreamManager:
    def __init__(self):
        # Un dictionnaire qui associe un ID de partie à une liste de "boîtes aux lettres" (files d'attente)
        self.listeners: Dict[int, List[asyncio.Queue]] = {}


    def add_listener(self, game_id: int):
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



#Construit l'état complet de la partie et le broadcast via SSE.
async def broadcast_game_update(game_id: int, session: Session):
    
    full_state = build_base_game_state(game_id, session)
    
    safe_state = jsonable_encoder(full_state) #pour convertir les datetime et autres types non JSON-serializable
    
    update_message = json.dumps({
        "event": "GAME_UPDATED",
        "game_state": safe_state
    })
    
    await stream_manager.broadcast(game_id, update_message)
    
    
