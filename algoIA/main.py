from __future__ import annotations

import os
# Désactive la recherche de transformations matérielles de MSMF
# Cela fait passer l'ouverture de 15 secondes à 0.5 seconde par caméra
os.environ["OPENCV_VIDEOIO_MSMF_ENABLE_HW_TRANSFORMS"] = "0"
import pathlib
import re
from dataclasses import dataclass
from pathlib import Path
from time import monotonic, sleep
import keyboard
import concurrent.futures # pour le traitement en parallèle des caméras
import threading

import cv2
import numpy as np
import requests
import onnxruntime as ort
"""Supprimer ces 4 lignes d'import nous fait gagner 20 secondes au démarrage"""
# import torch
# from fastai.vision.all import PILImage, load_learner, Pipeline
# from fastai.callback.wandb import WandbCallback
# from fastai.callback.tracker import SaveModelCallback, EarlyStoppingCallback

# -----------------------------------------------------------------------------
# Configuration générale
# -----------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent
IMAGE_DIR = PROJECT_ROOT / "saved_images"
HOMOGRAPHY_FILE = PROJECT_ROOT / "matrice_homographie"
MODEL_PATH = PROJECT_ROOT / "models_onnx" / "model_a_tester" / "final_resnet34_r15_1500.onnx"

IMAGE_DIR.mkdir(parents=True, exist_ok=True)
# Paramètres de détection du mouvement
MOTION_PIXEL_THRESHOLD = 25 # Seuil de changement de pixel pour détecter le mouvement
# MOTION_PIXEL_THRESHOLD = 25
# MOTION_AREA_THRESHOLD = 4000
MOTION_AREA_THRESHOLD = 6000 # Seuil de surface de mouvement pour déclencher la capture (ajusté pour éviter les faux positifs liés au bruit)
CAPTURE_DELAY_SECONDS = 0.5 # Temps entre la détection du mouvement et la capture des images (pour laisser le temps à la fléchette de se stabiliser)
CAPTURE_COOLDOWN_SECONDS = 1.0 # Temps minimum entre deux captures pour éviter les faux positifs successifs
LANCERS_PAR_SERIE = 3 # Nombre de lancers avant de demander une pause pour retirer les fléchettes
PAUSE_REFERENCE_PIXEL_THRESHOLD = 10 # Seuil de changement de pixel pour considérer que la cible a été modifiée (pour la pause)
PAUSE_REFERENCE_CHANGED_RATIO = 0.01 # Seuil de ratio de pixels modifiés pour détecter que la cible a été modifiée (pour la pause)

# Paramètres de post-traitement des masques
MASK_CLASS_INDEX = 1 # Classe Point
# rayon 15 : 600
# rayon 12 : 400
# rayon 10 : 300
# rayon 5 : 70
MIN_DART_CONTOUR_AREA = 100 # Adri: 200 --- Seuil d'aire pour filtrer les contours de fléchettes valides avec les fausses détections
MASK_MORPH_KERNEL_SIZE = 3 # Nettoyage des masques

# Paramètres backend
API_URL = os.getenv("DARTS_API_URL", "http://100.121.0.116:8000/throws/")
API_KEY = os.getenv("DARTS_API_KEY", "super_secret_key_for_raspberry_api_12345")
TARGET_ID = os.getenv("DARTS_TARGET_ID", "000001")

HEADERS = {"X-API-Key": API_KEY}


# FastAI peut charger un modèle exporté sous Linux sur Windows si l'on remplace
# PosixPath par WindowsPath avant l'appel à load_learner.
if pathlib.PosixPath is not pathlib.WindowsPath:
	pathlib.PosixPath = pathlib.WindowsPath


@dataclass
class CameraState:
	"""État mémorisé pour chaque caméra entre deux lancers."""

	previous_mask: np.ndarray | None = None
	previous_count: int = 0


@dataclass
class CameraDetection:
	"""Résultat brut d'une caméra pour un lancer donné."""

	camera_id: int
	mask: np.ndarray
	dart_count: int


def charger_matrice_par_defaut() -> dict[int, np.ndarray]:
	"""Retourne les matrices d'homographie connues pour les 3 caméras."""

	return {
		1: np.array(
			[
				[-1.64115188e+00,  2.34401619e+00,  1.64859287e+03],
				[-8.86771793e-02, -1.63297571e+00,  1.23236315e+03],
				[ 1.40486855e-04,  3.60742270e-03,  1.00000000e+00],
			],
			dtype=np.float32,
		),
		2: np.array(
			[
				[ 9.90516300e-01,  5.38173059e+00, -8.92113629e+02],
				[-1.65178972e+00,  3.07548616e+00,  9.96168790e+02],
				[ 3.86209146e-05,  4.00620287e-03,  1.00000000e+00],
			],
			dtype=np.float32,
		),
		3: np.array(
			[
				[ 9.60479652e-01, -2.74296660e-01,  7.52422043e+02],
				[ 1.63932267e+00,  2.86103741e+00, -1.18106739e+03],
				[ 1.61464379e-04,  3.71691123e-03,  1.00000000e+00],
			],
			dtype=np.float32,
		),
	}


def charger_homographies(path: Path) -> dict[int, np.ndarray]:
	"""Charge les homographies depuis le fichier de calibration si possible.

	Si le fichier n'est pas lisible, on retombe sur les valeurs codées en dur.
	"""

	default_matrices = charger_matrice_par_defaut()
	if not path.exists():
		print(f"[WARN] Fichier d'homographie introuvable : {path}")
		return default_matrices

	try:
		content = path.read_text(encoding="utf-8")
		float_pattern = r"[-+]?(?:\d*\.\d+|\d+)(?:[eE][-+]?\d+)?"
		matrices: dict[int, np.ndarray] = {}

		for camera_match in re.finditer(r"CAMERA\s+(\d+)\s*(\[\[.*?\]\])", content, re.S):
			camera_id = int(camera_match.group(1))
			matrix_text = camera_match.group(2)
			numbers = [float(value) for value in re.findall(float_pattern, matrix_text)]
			if len(numbers) != 9:
				raise ValueError(
					f"La matrice d'homographie de la caméra {camera_id} ne contient pas 9 valeurs."
				)
			matrices[camera_id] = np.array(numbers, dtype=np.float32).reshape(3, 3)

		if len(matrices) != 3:
			raise ValueError("Toutes les matrices d'homographie n'ont pas pu être extraites.")

		return matrices
	except Exception as exc:
		print(f"[WARN] Impossible de charger les homographies depuis le fichier : {exc}")
		return default_matrices


def preparer_image_pour_difference(frame: np.ndarray) -> np.ndarray:
	"""Convertit une image en niveaux de gris puis la lisse pour réduire le bruit."""

	gris = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
	gris = cv2.GaussianBlur(gris, (21, 21), 0)
	return gris


def calculer_score_mouvement(image_precedente: np.ndarray, image_actuelle: np.ndarray) -> float:
	"""Retourne un score de mouvement basé sur la différence entre deux frames."""

	difference = cv2.absdiff(image_precedente, image_actuelle)
	_, difference_binaire = cv2.threshold(
		difference,
		MOTION_PIXEL_THRESHOLD,
		255,
		cv2.THRESH_BINARY,
	)
	kernel = np.ones((MASK_MORPH_KERNEL_SIZE, MASK_MORPH_KERNEL_SIZE), dtype=np.uint8)
	difference_binaire = cv2.dilate(difference_binaire, kernel, iterations=2)
	contours, _ = cv2.findContours(difference_binaire, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
	return float(sum(cv2.contourArea(contour) for contour in contours))

def charger_modele():
    if not MODEL_PATH.exists():
        raise FileNotFoundError(f"Modèle introuvable : {MODEL_PATH}")
    
    # Options d'optimisation agressives
    sess_options = ort.SessionOptions()
    sess_options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
    sess_options.intra_op_num_threads = os.cpu_count() # Utilise tous les cœurs du processeur
    sess_options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
    
    providers = ['CPUExecutionProvider']
    if 'DmlExecutionProvider' in ort.get_available_providers():
        providers.insert(0, 'DmlExecutionProvider')
        
    session = ort.InferenceSession(str(MODEL_PATH), sess_options=sess_options, providers=providers)
    return session

def compter_flechettes_dans_masque(mask: np.ndarray, seuil: float = MIN_DART_CONTOUR_AREA):
	"""Compte les contours valides du masque, assimilés aux fléchettes détectées."""

	# cv2.RETR_TREE : tous les contours, y compris les trous internes
	contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE) #uniquement les contours externes
	return sum(1 for c in contours if cv2.contourArea(c) >= seuil)

def choisir_camera_detection(detections: list[CameraDetection]) -> CameraDetection:
    if not detections:
        raise ValueError("Aucune détection fournie.")
    # Renvoie la première caméra ayant le score max (plus rapide que random)
    return max(detections, key=lambda d: d.dart_count)

def isoler_nouvelle_fleche(mask_actuel: np.ndarray, masque_precedent: np.ndarray | None, kernel: np.ndarray) -> np.ndarray:
	"""Garde uniquement les pixels présents dans le masque actuel et absents du précédent."""

	if masque_precedent is None:
		return mask_actuel.copy()

	masque_inverse = cv2.bitwise_not(masque_precedent)
	masque_difference = cv2.bitwise_and(mask_actuel, masque_inverse)
	# masque_difference = cv2.morphologyEx(masque_difference, cv2.MORPH_OPEN, kernel, iterations=1)
	masque_difference = cv2.morphologyEx(masque_difference, cv2.MORPH_CLOSE, kernel, iterations=1)
	return masque_difference


def extraire_point_cible(mask: np.ndarray, seuil: float = MIN_DART_CONTOUR_AREA) -> tuple[int, int] | None:
	"""Récupère la position (x, y) du centre du plus grand contour du masque."""

	# cv2.RETR_TREE tous les contours, y compris les trous internes
	contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE) #uniquement les contours externes
	contours = [contour for contour in contours if cv2.contourArea(contour) >= seuil]
	if not contours:
		return None

	contour_principal = max(contours, key=cv2.contourArea)
	moments = cv2.moments(contour_principal)
	if moments["m00"] == 0:
		x, y, largeur, hauteur = cv2.boundingRect(contour_principal)
		cx, cy = x + largeur // 2, y + hauteur // 2
	else:
		cx = int(moments["m10"] / moments["m00"])
		cy = int(moments["m01"] / moments["m00"])
	return (cx, cy)


def appliquer_homographie(point: tuple[int, int], matrice_homographie: np.ndarray) -> tuple[float, float]:
	"""Projette un point de l'image inclinée vers l'image de référence."""

	point_numpy = np.array([[[float(point[0]), float(point[1])]]], dtype=np.float32)
	point_transforme = cv2.perspectiveTransform(point_numpy, matrice_homographie)
	return float(point_transforme[0, 0, 0]), float(point_transforme[0, 0, 1])


def envoyer_point_au_backend(x_impact: float, y_impact: float, camera_id: int) -> None:
	"""Envoie la position corrigée au backend."""

	payload = {
		"target_id": TARGET_ID,
		"x_position": float(x_impact),
		"y_position": float(y_impact),
		"camera_id": camera_id,
	}


	def sendCoord():
		t_req_start	= monotonic() # CHRONO RESEAU
		try:
			response = requests.post(API_URL, json=payload, headers=HEADERS, timeout=15)
			t_req_end = monotonic()

			if response.status_code == 200:
				data = response.json()
				print(f"[INFO] Fléchette enregistrée par le serveur (multiplicateur x{data.get('multiplier', '?')}).")
				print(f"[CHRONO] Envoi API réussi en : {(t_req_end - t_req_start):.3f} secondes")
			else:
				print(f"[ERREUR] Erreur API : {response.status_code} - {response.text}")
		except requests.exceptions.RequestException as exc:
			print(f"[ERREUR] Erreur de connexion au serveur : {exc}")

	# On lance l'envoi en arrière-plan !
	threading.Thread(target=sendCoord, daemon=True).start()

def analyser_lancer(
    ort_session,
    homographies: dict[int, np.ndarray],
    frames: dict[int, np.ndarray],
    states: dict[int, CameraState],
    nbLancer: int,
    meilleure_cam_id: int
) -> None:
    """Analyse un lancer en testant les 3 caméras, en commençant par la meilleure."""
    t_debut_analyse = monotonic()

    SCALE_FACTOR = 2
    NEW_WIDTH = 1280 // SCALE_FACTOR
    NEW_HEIGHT = 720 // SCALE_FACTOR
    SEUIL_AIRE_REDIMENSIONNE = MIN_DART_CONTOUR_AREA // (SCALE_FACTOR ** 2)

    kernel_size = max(1, MASK_MORPH_KERNEL_SIZE // SCALE_FACTOR)
    kernel = np.ones((kernel_size, kernel_size), np.uint8)

    # On tente les caméras dans l'ordre : meilleure_cam_id en premier, puis les autres
    autres_cams = [cid for cid in frames if cid != meilleure_cam_id]
    ordre_cameras = [meilleure_cam_id] + autres_cams

    point_camera = None
    cam_utilisee = None
    masque_actuel_final = None

    for cam_id in ordre_cameras:
        # 1. PRÉPARATION DE L'IMAGE
        img = frames[cam_id]
        img_resized = cv2.resize(img, (NEW_WIDTH, NEW_HEIGHT), interpolation=cv2.INTER_LINEAR)

        batch = np.expand_dims(img_resized[..., ::-1], axis=0).astype(np.float32)
        batch /= 255.0
        batch -= np.array([0.485, 0.456, 0.406], dtype=np.float32)
        batch /= np.array([0.229, 0.224, 0.225], dtype=np.float32)
        input_tensor = np.transpose(batch, (0, 3, 1, 2))

        # 2. INFÉRENCE
        t_onnx = monotonic()
        input_name = ort_session.get_inputs()[0].name
        preds = ort_session.run(None, {input_name: input_tensor})[0]
        masque_brut = np.argmax(preds, axis=1)[0]
        print(f"[INFO] Inférence caméra {cam_id} : {(monotonic() - t_onnx):.3f} sec")

        # 3. NETTOYAGE
        masque_actuel = (masque_brut == MASK_CLASS_INDEX).astype(np.uint8) * 255
        masque_actuel = cv2.morphologyEx(masque_actuel, cv2.MORPH_CLOSE, kernel, iterations=1)

        # Sauvegarde du masque pour debug
        chemin_masque = IMAGE_DIR / f"mask_cam{cam_id}_lancer{nbLancer}.png"
        cv2.imwrite(str(chemin_masque), masque_actuel)

        # 4. ISOLER LA NOUVELLE FLÉCHETTE
        etat = states[cam_id]
        masque_nouveau = isoler_nouvelle_fleche(masque_actuel, etat.previous_mask, kernel)

        print(f"[DEBUG] cam={cam_id} masque max={masque_actuel.max()} pixels_nouveau={np.count_nonzero(masque_nouveau)} seuil={SEUIL_AIRE_REDIMENSIONNE}")

        # Mise à jour du previous_mask pour cette caméra dans tous les cas
        if masque_actuel.max() > 0:
            etat.previous_mask = masque_actuel.copy()

        # 5. TENTATIVE DE DÉTECTION
        point_camera = extraire_point_cible(masque_nouveau, seuil=SEUIL_AIRE_REDIMENSIONNE)
        if point_camera is not None:
            cam_utilisee = cam_id
            masque_actuel_final = masque_actuel
            break  # On a trouvé — pas besoin d'analyser les autres caméras

        print(f"[WARN] Cam {cam_id} : aucune fléchette détectée, on essaie la suivante.")

    # 6. RÉSULTAT
    if point_camera is None or cam_utilisee is None:
        print(f"[ERREUR] Aucune fléchette trouvée sur aucune caméra.")
    else:
        point_original = (point_camera[0] * SCALE_FACTOR, point_camera[1] * SCALE_FACTOR)
        point_corrige = appliquer_homographie(point_original, homographies[cam_utilisee])
        print(f"[INFO] Point détecté sur cam {cam_utilisee} (échelle réduite) : {point_camera}")
        print(f"[INFO] Point corrigé : ({point_corrige[0]:.2f}, {point_corrige[1]:.2f})")
        envoyer_point_au_backend(point_corrige[0], point_corrige[1], cam_utilisee)

    print(f"[INFO] Analyse terminée en {(monotonic() - t_debut_analyse):.3f} sec")


def ouvrir_une_camera(camera_id):
	"""Tente d'ouvrir une seule caméra (Multithreadé)."""
	cap = cv2.VideoCapture(camera_id, cv2.CAP_MSMF) # on force explicitement l'api MSMF

	if cap.isOpened():
		cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
		cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
		cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, 0)
		return camera_id, cap
	else:
		print(f"Échec de la caméra {camera_id}.")
		return camera_id, None

def ouvrir_cameras() -> dict[int, cv2.VideoCapture]:
    """Ouvre les 3 caméras en parallèle"""
    cameras_ouvertes = {}
    camera_index = [3, 0, 2] # Les index des 3 caméras
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
        resultats = executor.map(ouvrir_une_camera, camera_index)
        for camera_index, cap in resultats:
            mapping = {3: 1 , 0: 2, 2: 3} 
            num_camera = mapping.get(camera_index)
            if cap is not None:
                cameras_ouvertes[num_camera] = cap
                print(f"[MAPPING] Caméra matérielle (Windows) {camera_index} associée à l'ID logiciel {num_camera}")
            else:
                raise RuntimeError(f"[ERREUR] Impossible d'ouvrir la caméra {num_camera}.")
    return cameras_ouvertes


def lire_images_reference(cameras):
    """Lit une image de référence pour chaque caméra au démarrage."""

    frames = {}
    for camera_id, camera in cameras.items():
        success, frame = camera.read()
        if not success:
            raise RuntimeError(f"[ERREUR] Impossible d'initialiser l'image de référence de la caméra {camera_id}.")
        frames[camera_id] = frame
    return frames


# def capturer_images_courantes(cameras):
# 	"""Lit une image sur chacune des 3 caméras."""

# 	frames = {}
# 	for camera_id, camera in cameras.items():
# 		success, frame = camera.read()
# 		if not success:
# 			raise RuntimeError(f"[ERREUR] Impossible de lire le flux vidéo de la caméra {camera_id}.")
# 		frames[camera_id] = frame
# 	return frames

def capturer_images_courantes(cameras):
    """Lit une image sur chacune des 3 caméras de manière synchronisée."""
    frames = {}
    
    # ordonne aux 3 caméras de figer la frame (très rapide)
    for camera in cameras.values():
        camera.grab()
        
    # récupère et décode les frames figées (plus lent, mais elles sont synchros !)
    for camera_id, camera in cameras.items():
        success, frame = camera.retrieve()
        if not success:
            raise RuntimeError(f"[ERREUR] Impossible de lire le flux de la caméra {camera_id}.")
        frames[camera_id] = frame
        
    return frames


def images_identiques(frames_a, frames_b):
	"""Vérifie que chaque caméra voit une image suffisamment proche de la référence."""

	if frames_a.keys() != frames_b.keys():
		return False

	for camera_id in frames_a:
		if frames_a[camera_id] is None or frames_b[camera_id] is None:
			return False

		reference_gray = preparer_image_pour_difference(frames_b[camera_id])
		current_gray = preparer_image_pour_difference(frames_a[camera_id])

		difference = cv2.absdiff(reference_gray, current_gray)
		changed_pixels = np.count_nonzero(difference > PAUSE_REFERENCE_PIXEL_THRESHOLD)
		changed_ratio = changed_pixels / difference.size
		if changed_ratio > PAUSE_REFERENCE_CHANGED_RATIO:
			return False

	return True


def attendre_reprise_apres_pause(
	cameras,
	camera_states,
	frames_reference,
):
	"""Attend que la cible redevienne vide avant de reprendre la partie.

	Pendant la pause, on remet aussi à zéro l'historique des caméras afin de
	repartir sur une nouvelle base après retrait des fléchettes.
	"""

	print("[PAUSE] Retirez les fléchettes de la cible.")

	stop = False
	while True:
		try:
			frames_actuelles = capturer_images_courantes(cameras)
			if images_identiques(frames_actuelles, frames_reference):
				print("[INFO] La cible est vide. La partie reprend dans 2 secondes...")
				sleep(2.0)
				print("[INFO] Go ! c'est reparti !\n")
				break
		except RuntimeError as exc:
			print(f"[WARN] Lecture caméra temporairement indisponible pendant la pause : {exc}")
			sleep(0.5)
			continue
		sleep(0.1)

		if keyboard.is_pressed('space'):
			stop = True
			print("Fin de la partie.")
			break

	for state in camera_states.values():
		state.previous_mask = None
		state.previous_count = 0

	return frames_reference, stop


def main() -> None:
	"""Boucle principale du système d'auto-scoring."""
	print("Chargement du modèle...")
	learner = charger_modele()
	print("Chargement de l'homographie...")
	homographies = charger_homographies(HOMOGRAPHY_FILE)
	print("Chargement des caméras...")
	cameras = ouvrir_cameras()

	print("Lecture des images de référence...")
	frames_reference = lire_images_reference(cameras)
	previous_gray = {
		camera_id: preparer_image_pour_difference(frame)
		for camera_id, frame in frames_reference.items()
	}
	camera_states = {camera_id: CameraState() for camera_id in cameras}

	print("La partie peut commencer !")
	derniere_capture = 0.0
	capture_en_attente = False
	instant_detection = 0.0
	lancers_depuis_pause = 0
	
	nbLancer = 0 # compteur de lancer pour le nommage des images sauvegardées(à supprimer plus tard)

	while True:
		frames_actuelles = capturer_images_courantes(cameras)
		current_gray = {
			camera_id: preparer_image_pour_difference(frame)
			for camera_id, frame in frames_actuelles.items()
		}

		scores = {
			camera_id: calculer_score_mouvement(previous_gray[camera_id], current_gray[camera_id])
			for camera_id in cameras
		}
		score_mouvement = max(scores.values())

		maintenant = monotonic()
		if (
			not capture_en_attente
			and score_mouvement > MOTION_AREA_THRESHOLD
			and (maintenant - derniere_capture) > CAPTURE_COOLDOWN_SECONDS
		):
			capture_en_attente = True
			instant_detection = maintenant
			print("Fléchette détectée ! Capture prévue dans 1/2 seconde.")

		if capture_en_attente and (maintenant - instant_detection) >= CAPTURE_DELAY_SECONDS:
			t_cap_start = monotonic() # CHRONO DEBUT CAPTURE

			frames_capturees = capturer_images_courantes(cameras)

			# --- LA MODIF EST ICI ---
			# On utilise les scores de mouvement calculés juste au-dessus pour déduire la bonne caméra
			meilleure_cam_id = max(scores, key=lambda camera_id: scores[camera_id])
   
			chemin_image = IMAGE_DIR / f"cam{meilleure_cam_id}_lancer{nbLancer}.jpg"
			if not cv2.imwrite(str(chemin_image), frames_capturees[meilleure_cam_id]):
				print(f"[ERREUR] Échec de l'enregistrement de {chemin_image}.")
			

			nbLancer += 1
			print(f"[CHRONO] Capture des 3 images : {(monotonic() - t_cap_start):.3f} secondes")
        
			print(f"--- En cours d'analyse de la caméra {meilleure_cam_id} uniquement ---")
            
			# On ajoute "meilleure_cam_id" en dernier paramètre
			analyser_lancer(learner, homographies, frames_capturees, camera_states, nbLancer, meilleure_cam_id)
			lancers_depuis_pause += 1

			capture_en_attente = False
			derniere_capture = maintenant

			print(f"\n--- En attente du lancer {nbLancer} ---")

			if lancers_depuis_pause >= LANCERS_PAR_SERIE:
				frames_reference, stop = attendre_reprise_apres_pause(cameras, camera_states, frames_reference)

				if stop:
					break
				
				previous_gray = {
					camera_id: preparer_image_pour_difference(frame)
					for camera_id, frame in frames_reference.items()
				}
				capture_en_attente = False
				derniere_capture = monotonic()
				lancers_depuis_pause = 0
				continue

		# Mise à jour des images de référence pour la prochaine différence de frame.
		previous_gray = current_gray

		if keyboard.is_pressed('esc'):
			print("Fin de la partie.")
			break
	
	for camera in cameras.values():
		camera.release()
	cv2.destroyAllWindows()


if __name__ == "__main__":
	main()
