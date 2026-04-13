#Attention, fonctionne si ca tourne sur raspberry
import subprocess
import logging

logger = logging.getLogger(__name__)

# Chemin absolu vers le dossier où se trouve le fichier de script sur le Raspberry Pi (a veriffffff)
SCRIPTS_PATH = "/home/pi/dartsify/"



# Lance un script LED en tâche de fond sans bloquer l'API
def trigger_led_script(animation_name: str):
    try:
        # tue toute ancienne animation qui serait encore en train de tourner
        subprocess.run(["pkill", "-f", f"{SCRIPTS_PATH}main.py"]) 
        
        # lance la nouvelle animation
        # Ligne de commande générée : python3 /home/pi/dartsify/main.py , win, ....
        subprocess.Popen(["python3", f"{SCRIPTS_PATH}main.py", animation_name])
        
        logger.info(f"Signal envoyé aux LEDs : {animation_name}")
    except Exception as e:
        logger.error(f"Erreur lors du lancement de l'animation LED : {e}")