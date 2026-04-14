#Attention, fonctionne si ca tourne sur raspberry
import subprocess
import logging

logger = logging.getLogger(__name__)

# Chemin absolu vers le dossier où se trouve le fichier de script sur le Raspberry Pi (a veriffffff)
SCRIPTS_PATH = "/home/pi/dartsify/leds/main.py"



# Lance un script LED en tâche de fond sans bloquer l'API
def trigger_led_script(action: str):
    try:
        # tue toute ancienne animation qui serait encore en train de tourner
        subprocess.run(["sudo", "pkill", "-f", SCRIPTS_PATH]) 
        
        # lance la nouvelle animation
        # Ligne de commande générée : python3 /home/pi/dartsify/main.py , win, ....
        subprocess.Popen(["sudo", "python3", SCRIPTS_PATH, action])
        
        logger.info(f"Signal LED envoyé : {action}")
    except Exception as e:
        logger.error(f"Erreur hardware lors du lancement de l'animation LED : {e}")