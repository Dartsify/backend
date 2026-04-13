#Attention, fonctionne si ca tourne sur raspberry
import subprocess
import logging

logger = logging.getLogger(__name__)

# Chemin absolu vers le dossier où se trouvent scripts sur le Raspberry Pi (a veriffffff)
SCRIPTS_PATH = "/home/pi/dartsify/led_scripts/"



# Lance un script LED en tâche de fond sans bloquer l'API
def trigger_led_script(script_name: str):
    try:
        # Popen lance le script dans un processus séparé (comme un thread) et rend la main immédiatement
        subprocess.Popen(["python3", f"{SCRIPTS_PATH}{script_name}"])
        logger.info(f"Animation LED lancée : {script_name}")
    except Exception as e:
        logger.error(f"Erreur lors du lancement de l'animation LED {script_name}: {e}")