import logging
from fastapi import Security, HTTPException
from fastapi.security import APIKeyHeader
from app.config import RASPBERRY_API_KEY

logger = logging.getLogger(__name__)

# On dit à FastAPI de chercher un en-tête appelé "X-API-Key" dans la requête
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=True)


#verif si bon raspberry
def verify_raspberry_pi(api_key: str = Security(api_key_header)) :
    if api_key != RASPBERRY_API_KEY:
        logger.warning("Une machine non autorisée a tenté d'envoyer un lancer !")
        raise HTTPException(status_code=403, detail="Accès refusé. Matériel non autorisé.")
    return True


