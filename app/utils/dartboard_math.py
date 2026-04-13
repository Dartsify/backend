import math

# Les 20 secteurs dans l'ordre des aiguilles d'une montre en partant de midi (12h)
SECTORS = [20, 1, 18, 4, 13, 6, 10, 15, 2, 17, 3, 19, 7, 16, 8, 11, 14, 9, 12, 5]

def get_score_and_multiplier(x: float, y: float) -> tuple[int, int]:
    # Centre de l'image (en pixels) 
    CENTER_X = 582
    CENTER_Y = 727
    
    # Rayons (en pixels)
    R_BULL_INNER = 12      # Fin du double bull
    R_BULL_OUTER = 36      # Fin du simple bull
    R_TRIPLE_INNER = 236   # Début du triple
    R_TRIPLE_OUTER = 258   # Fin du triple
    R_DOUBLE_INNER = 390   # Début du double
    R_DOUBLE_OUTER = 417   # Fin du double (bord de la zone de jeu)

    # Calcul de distance par rapport au centre
    dx = x - CENTER_X
    # dy est inversé car ici image numérique, le pixel Y=0 est tout en haut (a gauche)
    dy = CENTER_Y - y 
    
    # Calcul de distance (Pythagore)
    distance = math.hypot(dx, dy)

    # Vérification centrale et sortie de cible avant de calculer l'angle
    if distance <= R_BULL_INNER:
        return 50, 2  # Double Bull (Le multiplicateur = 2)
    if distance <= R_BULL_OUTER:
        return 25, 1  # Simple Bull 
    if distance > R_DOUBLE_OUTER:
        return 0, 1   # Hors cible (Miss)

    # Calcul de Angle (secteur)
    # atan2 donne l'angle par rapport à la droite (3h). On le convertit en degrés.
    angle_rad = math.atan2(dy, dx)
    angle_deg = math.degrees(angle_rad)
    
    # On décale les axes pour que 0° soit exactement en haut (12h au milieu de la zone du 20) et on tourne à droite (horaire)
    adjusted_angle = (90 - angle_deg) % 360
    
    # Chaque secteur fait 18°. On décale de +9° pour que le secteur 20 (en haut) soit bien centré sur 0°
    sector_index = int(((adjusted_angle + 9) % 360) / 18)
    base_score = SECTORS[sector_index]

    # Vérif des multiplicateurs
    if R_TRIPLE_INNER <= distance <= R_TRIPLE_OUTER:
        return base_score, 3 
    elif R_DOUBLE_INNER <= distance <= R_DOUBLE_OUTER:
        return base_score, 2
    else:
        return base_score, 1