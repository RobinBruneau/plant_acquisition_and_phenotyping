import os
import time
import random
import base64
from datetime import datetime
from flask import Flask, request, jsonify

app = Flask(__name__)

# --- CONFIGURATION DU CHEMIN CIBLE SUR VOTRE MACHINE ---
TARGET_BASE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data_app")

# Pixel PNG 1x1 transparent en binaire
PNG_BYTES = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII="
)

@app.after_request
def add_cors_headers(response):
    """Autorise la page web locale à communiquer avec le serveur Python."""
    response.headers['Access-Control-Allow-Origin'] = '*'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type'
    response.headers['Access-Control-Allow-Methods'] = 'POST, OPTIONS'
    return response

@app.route("/api/save_acquisition", methods=["POST", "OPTIONS"])
def save_acquisition():
    if request.method == "OPTIONS":
        return jsonify({"status": "ok"}), 200

    try:
        data = request.get_json(force=True, silent=True) or {}
        experiment = data.get("experiment", "default_exp")
        sample_id = data.get("sample_id", "default_sample")

        # --- 1. DÉLAI INITIAL DE 10 SECONDES ---
        print(f"[{datetime.now().strftime('%H:%M:%S')}] Requête reçue. Attente de 10 secondes avant de démarrer la création...")
        

        # Format de la date du jour : YYYY-MM-DD
        date_jour = datetime.now().strftime("%Y-%m-%d")

        # Construction du chemin : /chemin/.../data_app/nom_acquisition/YYYY-MM-DD/
        target_dir = os.path.join(TARGET_BASE_DIR, experiment, date_jour)

        # Création automatique de toute l'arborescence de dossiers
        os.makedirs(target_dir, exist_ok=True)

        # --- 2. CRÉATION PROGRESSIVE DES 36 IMAGES (1 à 3s d'intervalle) ---
        print(f"[{datetime.now().strftime('%H:%M:%S')}] Début de la génération des 36 images dans : {target_dir}")
        
        fichiers_crees = []
        for i in range(1, 37):
            num_str = f"{i:03d}"  # 001, 002, ..., 036
            filename = f"{num_str}_{sample_id}.png"
            filepath = os.path.join(target_dir, filename)

            # Pause aléatoire entre 1 et 3 secondes avant chaque image
            delay = 0.1
            time.sleep(delay)

            with open(filepath, "wb") as f:
                f.write(PNG_BYTES)
            
            fichiers_crees.append(filename)
            print(f"  [{i}/36] Image créée : {filename} (après {delay:.1f}s)")

        print(f"[{datetime.now().strftime('%H:%M:%S')}] [Succès] Acquisition terminée ! 36 PNGs écrits.")
        return jsonify({
            "status": "success",
            "path": target_dir,
            "count": len(fichiers_crees)
        }), 200

    except Exception as e:
        print(f"[Erreur Écriture] : {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


if __name__ == "__main__":
    print(f"Serveur de pont démarré sur http://localhost:5000")
    print(f"Dossier cible : {TARGET_BASE_DIR}")
    app.run(host="127.0.0.1", port=5000, debug=False)