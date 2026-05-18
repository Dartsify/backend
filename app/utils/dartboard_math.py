import math

# Les 20 secteurs dans l'ordre des aiguilles d'une montre en partant de midi (12h)
SECTORS = [20, 1, 18, 4, 13, 6, 10, 15, 2, 17, 3, 19, 7, 16, 8, 11, 14, 9, 12, 5]



# Constantes universelles de calibration (post-homographie et basées sur les rayons identifiés)
CENTER_X = 642
CENTER_Y = 356
R_BULL_INNER = 8
R_BULL_OUTER = 24
R_TRIPLE_INNER = 139
R_TRIPLE_OUTER = 155
R_DOUBLE_INNER = 235
R_DOUBLE_OUTER = 251



#calcul du score et multiplicateur en fct de X et Y (on garde le cam id pour tester si probleme sur une camera en particulier)
def get_score_and_multiplier(x: float, y: float, camera_id: int) -> tuple[int, int]:
    
    # Calcul de distance par rapport au centre de la cible
    dx = x - CENTER_X
    dy = CENTER_Y - y # Y=0 en haut a gauche
    
    # Calcul de distance grâce à Pythagore
    distance = math.hypot(dx, dy)

    # Vérification du centre et sortie de cible avant de calculer l'angle
    if distance <= R_BULL_INNER :
        return 25, 2  # Double Bull (multiplicateur = 2)
    if distance <= R_BULL_OUTER:
        return 25, 1  # Simple Bull 
    if distance > R_DOUBLE_OUTER:
        return 0, 1   # Hors cible (Raté)

    # Calcul d'angle (secteur)
    # atan2 donne l'angle par rapport à la droite (3h) -> converti en degrés
    angle_rad = math.atan2(dy, dx)
    angle_deg = math.degrees(angle_rad)
    
    # On décale les axes pour que 0° soit exactement en haut et on tourne à droite
    adjusted_angle = (90 - angle_deg) % 360
    
    # Chaque secteur fait 18°. On décale de +9° pour que le secteur 20 soit bien centré
    sector_index = int(((adjusted_angle + 9) % 360) / 18)
    base_score = SECTORS[sector_index]

    # Vérification des multiplicateurs
    if R_TRIPLE_INNER <= distance <= R_TRIPLE_OUTER:
        return base_score, 3 
    elif R_DOUBLE_INNER <= distance <= R_DOUBLE_OUTER:
        return base_score, 2
    else:
        return base_score, 1


# # Ajuste les légères différences de calibrage (centre et zoom) post-homographie
# # pour aligner tous les points sur le référentiel de la Caméra 1. pour envoyer au front  ---->> Plus besoin car homographie améliorée et universelle
# def map_to_master_camera(x: float, y: float, camera_id: int) -> tuple[float, float]:
    
#     # Si c'est déjà la caméra 1 (ou non défini), on ne touche à rien
#     if camera_id == 1 or camera_id is None or camera_id not in CAMERAS_CALIBRATION:
#         return x, y 

#     calib = CAMERAS_CALIBRATION[camera_id]
#     master_calib = CAMERAS_CALIBRATION[1]

#     dx = x - calib["CENTER_X"]
#     dy = y - calib["CENTER_Y"]

#     # ajuste la micro-différence d'échelle (ex: 247 / 245 = 1.008)
#     scale_ratio = master_calib["R_DOUBLE_OUTER"] / calib["R_DOUBLE_OUTER"]
#     dx *= scale_ratio
#     dy *= scale_ratio

#     final_x = dx + master_calib["CENTER_X"]
#     final_y = dy + master_calib["CENTER_Y"]

#     return round(final_x, 1), round(final_y, 1)