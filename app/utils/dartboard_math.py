import math

# Les 20 secteurs dans l'ordre des aiguilles d'une montre en partant de midi (12h)
SECTORS = [20, 1, 18, 4, 13, 6, 10, 15, 2, 17, 3, 19, 7, 16, 8, 11, 14, 9, 12, 5]



CAMERAS_CALIBRATION = { # Ces valeurs sont à ajuster en fonction de la configuration réelle de chaque caméra (1 2 et 3)
    1: {
        "CENTER_X": 624,
        "CENTER_Y": 325,
        "R_BULL_INNER": 8,
        "R_BULL_OUTER": 22,
        "R_TRIPLE_INNER": 138,
        "R_TRIPLE_OUTER": 151,
        "R_DOUBLE_INNER": 227,
        "R_DOUBLE_OUTER": 247
    },
    
    2: {
        
        "CENTER_X": 631,
        "CENTER_Y": 332,
        "R_BULL_INNER": 8,
        "R_BULL_OUTER": 22,
        "R_TRIPLE_INNER": 138,
        "R_TRIPLE_OUTER": 152,
        "R_DOUBLE_INNER": 227,
        "R_DOUBLE_OUTER": 245
    },
    
    3: {
        
        "CENTER_X": 622,
        "CENTER_Y": 333,
        "R_BULL_INNER": 12,
        "R_BULL_OUTER": 20,
        "R_TRIPLE_INNER": 137,
        "R_TRIPLE_OUTER": 150,
        "R_DOUBLE_INNER": 229,
        "R_DOUBLE_OUTER": 243
    }
}




def get_score_and_multiplier(x: float, y: float, camera_id: int) -> tuple[int, int]:
    
    # récupération des dimensions de la bonne caméra (fallback sur la 1 si erreur)
    calib = CAMERAS_CALIBRATION.get(camera_id, CAMERAS_CALIBRATION[1])
    
    # Calcul de distance par rapport au centre spécifique de cette caméra
    dx = x - calib["CENTER_X"]
    dy = calib["CENTER_Y"] - y # Y=0 en haut a gauche
    
    # Calcul de la distance grâce à Pythagore
    distance = math.hypot(dx, dy)

    # Vérification du centre et sortie de cible avant de calculer l'angle
    if distance <= calib["R_BULL_INNER"]:
        return 50, 2  # Double Bull (multiplicateur = 2)
    if distance <= calib["R_BULL_OUTER"]:
        return 25, 1  # Simple Bull 
    if distance > calib["R_DOUBLE_OUTER"]:
        return 0, 1   # Hors cible (Raté)

    # Calcul d'angle (secteur)
    # atan2 donne l'angle par rapport à la droite (3h). On le convertit en degrés
    angle_rad = math.atan2(dy, dx)
    angle_deg = math.degrees(angle_rad)
    
    # On décale les axes pour que 0° soit exactement en haut et on tourne à droite
    adjusted_angle = (90 - angle_deg) % 360
    
    # Chaque secteur fait 18°. On décale de +9° pour que le secteur 20 soit bien centré
    sector_index = int(((adjusted_angle + 9) % 360) / 18)
    base_score = SECTORS[sector_index]

    # Vérification des multiplicateurs
    if calib["R_TRIPLE_INNER"] <= distance <= calib["R_TRIPLE_OUTER"]:
        return base_score, 3 
    elif calib["R_DOUBLE_INNER"] <= distance <= calib["R_DOUBLE_OUTER"]:
        return base_score, 2
    else:
        return base_score, 1