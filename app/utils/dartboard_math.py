import math
#Le fichier est fait pour que les rayons soeint en milimetres !!
#Si David les renvois en pixels il faudra changer ca!!!

# Les 20 secteurs dans l'ordre des aiguilles d'une montre
SECTORS = [20, 1, 18, 4, 13, 6, 10, 15, 2, 17, 3, 19, 7, 16, 8, 11, 14, 9, 12, 5]

def get_score_and_multiplier(x: float, y: float) -> tuple[int, int]:
    #il faut transformer les coordonnees en points (en principe le bull sera en 0.0)
    
    # Important : RAYONS a ADAPTER !!!!!!!
    R_BULL_INNER = 6.35    # Rayon du double bull
    R_BULL_OUTER = 15.9    # Rayon du simple bull
    R_TRIPLE_INNER = 99.0  # Début du triple
    R_TRIPLE_OUTER = 107.0 # Fin du triple
    R_DOUBLE_INNER = 162.0 # Début du double
    R_DOUBLE_OUTER = 170.0 # Fin du double (bord de la zone de jeu)

    # Calcul de distance depuis le centre (Pythagore)
    distance = math.hypot(x, y)

    # Verif rapide : Est-on dans le centre ou hors de la cible ?
    if distance <= R_BULL_INNER:
        return 50, 2  # Double Bull (50 points, Multiplicateur 2)
    if distance <= R_BULL_OUTER:
        return 25, 1  # Simple Bull (25 points, Multiplicateur 1)
    if distance > R_DOUBLE_OUTER:
        return 0, 1   # Hors cible (0 point)

    # Calcul de l'angle pour savoir dans quel "Secteur" (de 1 à 20) on est
    # atan2 donne l'angle. On le convertit en degrés
    angle_rad = math.atan2(y, x)
    angle_deg = math.degrees(angle_rad)
    
    # 0° à droite (3h) et 90° en haut (12h) 
    # On décale les axes pour que 0° soit exactement en haut (sur le 20) et tourne à droite
    adjusted_angle = (90 - angle_deg) % 360
    
    # Chaque secteur fait 18°. On décale de +9° pour que le secteur 20 (en haut) soit bien centré sur 0°
    sector_index = int(((adjusted_angle + 9) % 360) / 18)
    base_score = SECTORS[sector_index]

    # On regarde la distance pour savoir si on est tombé dans l'anneau des Doubles ou Triples
    if R_TRIPLE_INNER <= distance <= R_TRIPLE_OUTER:
        return base_score * 3, 3
    elif R_DOUBLE_INNER <= distance <= R_DOUBLE_OUTER:
        return base_score * 2, 2
    else:
        return base_score, 1