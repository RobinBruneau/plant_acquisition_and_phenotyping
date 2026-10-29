import os
import sys
import json
import subprocess
import tkinter as tk
import time
from datetime import datetime, date
from PIL import Image, ImageTk
import pyautogui
import numpy as np

# ==========================================
# CONFIGURATION
# ==========================================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Dossier où les acquisitions sont enregistrées
DOSSIER_DATA_APP = os.path.join(os.path.dirname(BASE_DIR), "data_app")
DOSSIER_SAUVEGARDE = DOSSIER_DATA_APP  # Référence principale pour le cloud

FICHIER_WEB = os.path.join(BASE_DIR, "index.html")
FICHIER_CALIBRATION = os.path.join(BASE_DIR, "calibration_zones.json")

# Configuration Rclone (Remote: "geneva")
RCLONE_REMOTE_NAME = "geneva"
RCLONE_REMOTE_FOLDER = "Acquisitions"
RCLONE_REMOTE_PATH = f"{RCLONE_REMOTE_NAME}:{RCLONE_REMOTE_FOLDER}"

# Liste des 11 zones de calibration
ZONES_CONFIG = [
    {"id": "nav_init_shutdown", "label": "Nav: Init/Shutdown", "color": "#2196F3"},
    {"id": "nav_recording", "label": "Nav: Recording", "color": "#00BCD4"},
    {"id": "btn_sub_initialize", "label": "Sub: Initialize", "color": "#4CAF50"},
    {"id": "btn_sub_shutdown", "label": "Sub: Shutdown", "color": "#F44336"},
    {"id": "experiment", "label": "Experiment Field", "color": "#FF5722"},
    {"id": "sample_id", "label": "Sample ID Field", "color": "#FFC107"},
    {"id": "dropdown_config", "label": "Dropdown Config", "color": "#9C27B0"},
    {"id": "option_0_180", "label": "Option 0-180", "color": "#3F51B5"},
    {"id": "option_180_360", "label": "Option 180-360", "color": "#673AB7"},
    {"id": "record", "label": "Record (F1)", "color": "#8BC34A"},
    {"id": "config_area", "label": "Config Area (Green/Gray)", "color": "#E91E63"}
]

if not os.path.exists(DOSSIER_DATA_APP):
    os.makedirs(DOSSIER_DATA_APP, exist_ok=True)


# ==========================================
# CLIPBOARD MANAGEMENT
# ==========================================
def copier_dans_presse_papier(texte):
    try:
        import pyperclip
        pyperclip.copy(texte)
        return
    except ImportError:
        pass

    try:
        process = subprocess.Popen(['xclip', '-selection', 'clipboard'], stdin=subprocess.PIPE)
        process.communicate(input=texte.encode('utf-8'))
        return
    except Exception:
        pass

    try:
        process = subprocess.Popen(['xsel', '-b', '-i'], stdin=subprocess.PIPE)
        process.communicate(input=texte.encode('utf-8'))
        return
    except Exception:
        pass


# ==========================================
# CALIBRATION SAVE & LOAD
# ==========================================
def sauvegarder_zones(rectangles_data):
    with open(FICHIER_CALIBRATION, "w") as f:
        json.dump(rectangles_data, f, indent=4)


def charger_zones():
    if os.path.exists(FICHIER_CALIBRATION):
        try:
            with open(FICHIER_CALIBRATION, "r") as f:
                return json.load(f)
        except Exception:
            return None
    return None


# ==========================================
# CALIBRATION EDITOR
# ==========================================
class EditeurCalibration(tk.Toplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.parent = parent
        self.attributes("-fullscreen", True)
        self.attributes("-topmost", True)
        self.title("Calibration Editor")

        self.screen_w, self.screen_h = pyautogui.size()

        screenshot = pyautogui.screenshot()
        self.bg_image = ImageTk.PhotoImage(screenshot)

        self.canvas = tk.Canvas(self, highlightthickness=0, bg="#1e1e2e")
        self.canvas.pack(fill=tk.BOTH, expand=True)
        self.canvas.create_image(0, 0, image=self.bg_image, anchor=tk.NW)

        overlay = Image.new('RGBA', (self.screen_w, self.screen_h), (18, 18, 30, 110))
        self.overlay_img = ImageTk.PhotoImage(overlay)
        self.canvas.create_image(0, 0, image=self.overlay_img, anchor=tk.NW)

        self.rects_data = charger_zones()
        self.items = {}
        self.active_item = None
        self.mode = None
        self.drag_start = (0, 0)

        self._dessiner_panneau_droite()
        self._initialiser_rectangles()

        self.canvas.bind("<ButtonPress-1>", self.on_press)
        self.canvas.bind("<B1-Motion>", self.on_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_release)
        self.bind("<Return>", lambda e: self.valider())
        self.bind("<Escape>", lambda e: self.annuler())

    def _dessiner_panneau_droite(self):
        x1 = self.screen_w - 700
        y1 = 10
        x2 = x1 + 675
        y2 = y1 + 980

        self.canvas.create_rectangle(
            x1, y1, x2, y2, fill="#1e1e2e", outline="#2b2b3d", width=3
        )

        self.canvas.create_rectangle(
            x1 + 30, y1 + 20, x2 - 30, y1 + 70,
            fill="#2196f3", outline="", width=0
        )
        self.canvas.create_text(
            (x1 + x2) // 2, y1 + 45,
            text="CALIBRATION MODE (11 ZONES)", fill="white", font=("Segoe UI", 15, "bold")
        )

        card_y1 = y1 + 80
        card_y2 = card_y1 + 750
        self.canvas.create_rectangle(
            x1 + 30, card_y1, x2 - 30, card_y2,
            fill="#2b2b3d", outline="", width=0
        )
        self.canvas.create_text(
            x1 + 54, card_y1 + 20, text="ZONE COLOR LEGEND", anchor=tk.W,
            fill="#8a8a9e", font=("Segoe UI", 12, "bold")
        )

        for idx, z in enumerate(ZONES_CONFIG):
            item_y = card_y1 + 45 + idx * 63
            self.canvas.create_rectangle(
                x1 + 40, item_y, x1 + 85, item_y + 35,
                fill=z["color"], outline="", width=0
            )
            self.canvas.create_text(
                x1 + 100, item_y + 17, text=z["label"], anchor=tk.W,
                fill="#e0e0e0", font=("Segoe UI", 12, "bold")
            )

        btn_save_y1 = card_y2 + 15
        btn_save_y2 = btn_save_y1 + 60
        self.btn_save_coords = (x1 + 30, btn_save_y1, x2 - 30, btn_save_y2)
        self.canvas.create_rectangle(
            self.btn_save_coords[0], self.btn_save_coords[1],
            self.btn_save_coords[2], self.btn_save_coords[3],
            fill="#4caf50", outline="", width=0
        )
        self.canvas.create_text(
            (self.btn_save_coords[0] + self.btn_save_coords[2]) // 2,
            (self.btn_save_coords[1] + self.btn_save_coords[3]) // 2,
            text="Save Calibration (Enter)", fill="white", font=("Segoe UI", 15, "bold")
        )

        btn_cancel_y1 = btn_save_y2 + 10
        btn_cancel_y2 = btn_cancel_y1 + 50
        self.btn_cancel_coords = (x1 + 30, btn_cancel_y1, x2 - 30, btn_cancel_y2)
        self.canvas.create_rectangle(
            self.btn_cancel_coords[0], self.btn_cancel_coords[1],
            self.btn_cancel_coords[2], self.btn_cancel_coords[3],
            fill="#3a3a52", outline="", width=0
        )
        self.canvas.create_text(
            (self.btn_cancel_coords[0] + self.btn_cancel_coords[2]) // 2,
            (self.btn_cancel_coords[1] + self.btn_cancel_coords[3]) // 2,
            text="Cancel (Esc)", fill="white", font=("Segoe UI", 13, "bold")
        )

    def _initialiser_rectangles(self):
        grid_cols = 2
        default_w, default_h = 180, 80

        for idx, z in enumerate(ZONES_CONFIG):
            zid = z["id"]
            color = z["color"]

            if self.rects_data and zid in self.rects_data:
                r = self.rects_data[zid]
                x1 = int(r["rx1"] * self.screen_w)
                y1 = int(r["ry1"] * self.screen_h)
                x2 = int(r["rx2"] * self.screen_w)
                y2 = int(r["ry2"] * self.screen_h)
            else:
                col = idx % grid_cols
                row = idx // grid_cols
                x1 = 80 + col * 220
                y1 = 60 + row * 110
                x2 = x1 + default_w
                y2 = y1 + default_h

            rect_id = self.canvas.create_rectangle(
                x1, y1, x2, y2, outline=color, width=4, fill=color, stipple="gray25"
            )
            text_id = self.canvas.create_text(
                (x1 + x2) // 2, (y1 + y2) // 2, text=z["label"],
                fill="white", font=("Segoe UI", 11, "bold")
            )
            handle_id = self.canvas.create_rectangle(
                x2 - 12, y2 - 12, x2, y2, fill="white", outline=color, width=2
            )

            self.items[zid] = {
                "rect": rect_id, "text": text_id, "handle": handle_id,
                "color": color, "label": z["label"]
            }

    def on_press(self, event):
        x, y = event.x, event.y

        if self.btn_save_coords[0] <= x <= self.btn_save_coords[2] and self.btn_save_coords[1] <= y <= self.btn_save_coords[3]:
            self.valider()
            return

        if self.btn_cancel_coords[0] <= x <= self.btn_cancel_coords[2] and self.btn_cancel_coords[1] <= y <= self.btn_cancel_coords[3]:
            self.annuler()
            return

        self.active_item = None
        self.mode = None

        for zid, item in self.items.items():
            hx1, hy1, hx2, hy2 = self.canvas.coords(item["handle"])
            if hx1 <= x <= hx2 and hy1 <= y <= hy2:
                self.active_item = zid
                self.mode = "resize"
                self.drag_start = (x, y)
                return

            rx1, ry1, rx2, ry2 = self.canvas.coords(item["rect"])
            if rx1 <= x <= rx2 and ry1 <= y <= ry2:
                self.active_item = zid
                self.mode = "move"
                self.drag_start = (x, y)
                return

    def on_drag(self, event):
        if not self.active_item:
            return

        dx = event.x - self.drag_start[0]
        dy = event.y - self.drag_start[1]
        self.drag_start = (event.x, event.y)

        item = self.items[self.active_item]
        rx1, ry1, rx2, ry2 = self.canvas.coords(item["rect"])

        if self.mode == "move":
            self.canvas.move(item["rect"], dx, dy)
            self.canvas.move(item["text"], dx, dy)
            self.canvas.move(item["handle"], dx, dy)

        elif self.mode == "resize":
            new_x2 = max(rx1 + 10, rx2 + dx)
            new_y2 = max(ry1 + 10, ry2 + dy)
            self.canvas.coords(item["rect"], rx1, ry1, new_x2, new_y2)
            self.canvas.coords(item["text"], (rx1 + new_x2) // 2, (ry1 + new_y2) // 2)
            self.canvas.coords(item["handle"], new_x2 - 12, new_y2 - 12, new_x2, new_y2)

    def on_release(self, event):
        self.active_item = None
        self.mode = None

    def valider(self):
        export_data = {}
        for zid, item in self.items.items():
            x1, y1, x2, y2 = self.canvas.coords(item["rect"])
            export_data[zid] = {
                "rx1": x1 / self.screen_w,
                "ry1": y1 / self.screen_h,
                "rx2": x2 / self.screen_w,
                "ry2": y2 / self.screen_h,
            }

        sauvegarder_zones(export_data)
        self.destroy()
        self.parent.deiconify()
        afficher_status("Calibration saved successfully!", "#81c784")

    def annuler(self):
        self.destroy()
        self.parent.deiconify()


# ==========================================
# AUTOMATION & COLOR DETECTION FUNCTIONS
# ==========================================
def ouvrir_application_web():
    if not os.path.exists(FICHIER_WEB):
        afficher_status(f"Error: '{FICHIER_WEB}' not found.", "#e57373")
        return

    try:
        if sys.platform.startswith('win'):
            os.startfile(FICHIER_WEB)
        elif sys.platform.startswith('darwin'):
            subprocess.Popen(['open', FICHIER_WEB])
        else:
            subprocess.Popen(['xdg-open', FICHIER_WEB])

        afficher_status("Web application opened.", "#e0e0e0")
    except Exception as e:
        afficher_status(f"Opening error: {e}", "#e57373")


def ouvrir_calibration():
    app.withdraw()
    app.after(200, lambda: EditeurCalibration(app))


def get_coords_zone(zone_id):
    data = charger_zones()
    if not data or zone_id not in data:
        return None
    sw, sh = pyautogui.size()
    z = data[zone_id]
    x1, y1 = int(z["rx1"] * sw), int(z["ry1"] * sh)
    x2, y2 = int(z["rx2"] * sw), int(z["ry2"] * sh)
    cx, cy = (x1 + x2) // 2, (y1 + y2) // 2
    return cx, cy, x1, y1, x2, y2


def cliquer_zone(zone_id):
    coords = get_coords_zone(zone_id)
    if not coords:
        return False, f"Zone '{zone_id}' not calibrated."
    cx, cy, _, _, _, _ = coords

    try:
        pyautogui.click(cx, cy)
        return True, (cx, cy)
    except Exception as e:
        return False, str(e)


def survoler_zone(zone_id):
    coords = get_coords_zone(zone_id)
    if not coords:
        return False
    cx, cy, _, _, _, _ = coords
    pyautogui.moveTo(cx, cy)
    return True


def saisir_texte_zone(zone_id, texte):
    succes, msg = cliquer_zone(zone_id)
    if not succes:
        return False, msg

    time.sleep(0.2)
    copier_dans_presse_papier(texte)

    pyautogui.hotkey('ctrl', 'a')
    time.sleep(0.1)
    pyautogui.press('backspace')
    time.sleep(0.1)

    pyautogui.hotkey('ctrl', 'v')
    time.sleep(0.1)
    return True, f"Text '{texte}' pasted."


# --- DETECTEURS DE COULEURS ---
def verifier_couleur_verte(zone_id):
    coords = get_coords_zone(zone_id)
    if not coords:
        return False
    _, _, x1, y1, x2, y2 = coords

    screenshot = pyautogui.screenshot(region=(max(0, x1), max(0, y1), max(1, x2 - x1), max(1, y2 - y1)))
    img_np = np.array(screenshot)

    masque = (img_np[:, :, 0] > 100) & (img_np[:, :, 0] < 170) & \
             (img_np[:, :, 1] > 170) & \
             (img_np[:, :, 2] < 100)
    return np.sum(masque) > 10


def verifier_couleur_rouge(zone_id):
    coords = get_coords_zone(zone_id)
    if not coords:
        return False
    _, _, x1, y1, x2, y2 = coords

    screenshot = pyautogui.screenshot(region=(max(0, x1), max(0, y1), max(1, x2 - x1), max(1, y2 - y1)))
    img_np = np.array(screenshot)

    masque = (img_np[:, :, 0] > 200) & (img_np[:, :, 1] < 100) & (img_np[:, :, 2] < 100)
    return np.sum(masque) > 10


def verifier_couleur_bleue(zone_id):
    coords = get_coords_zone(zone_id)
    if not coords:
        return False
    _, _, x1, y1, x2, y2 = coords

    screenshot = pyautogui.screenshot(region=(max(0, x1), max(0, y1), max(1, x2 - x1), max(1, y2 - y1)))
    img_np = np.array(screenshot)

    masque = (img_np[:, :, 0] < 50) & (img_np[:, :, 1] > 90) & (img_np[:, :, 1] < 150) & (img_np[:, :, 2] > 170)
    return np.sum(masque) > 10


def verifier_config_grise(zone_id):
    coords = get_coords_zone(zone_id)
    if not coords:
        return False
    _, _, x1, y1, x2, y2 = coords

    screenshot = pyautogui.screenshot(region=(max(0, x1), max(0, y1), max(1, x2 - x1), max(1, y2 - y1)))
    img_np = np.array(screenshot)

    diff_rg = np.abs(img_np[:, :, 0].astype(int) - img_np[:, :, 1].astype(int))
    diff_gb = np.abs(img_np[:, :, 1].astype(int) - img_np[:, :, 2].astype(int))
    masque = (diff_rg < 15) & (diff_gb < 15) & (img_np[:, :, 0] > 160) & (img_np[:, :, 0] < 220)
    return np.sum(masque) > 50


def attendre_fin_enregistrement(zone_config_id, timeout_sec=120):
    start = time.time()
    time.sleep(0.5)
    
    while time.time() - start < timeout_sec:
        if verifier_couleur_verte(zone_config_id):
            return True
        time.sleep(0.5)
        app.update()
    return False


def definir_etat_acquisition(en_cours):
    if en_cours:
        lbl_etat.config(text="ACQUISITION IN PROGRESS", bg="#f44336", fg="white")
    else:
        lbl_etat.config(text="STANDBY / READY", bg="#4caf50", fg="white")
    app.update()


# ==========================================
# SHUTDOWN AUTOMATIQUE DE LA MACHINE
# ==========================================
def arreter_machine():
    if not charger_zones():
        afficher_status("Cannot perform shutdown: Zones not calibrated.", "#e57373")
        return False

    afficher_status("Shutdown protocol: Switching to Init/Shutdown tab...", "#ffb74d")
    cliquer_zone("nav_init_shutdown")
    time.sleep(0.5)

    start_time = time.time()
    while not verifier_couleur_verte("nav_init_shutdown") and time.time() - start_time < 3:
        time.sleep(0.2)
        app.update()

    if verifier_couleur_rouge("btn_sub_shutdown"):
        afficher_status("Machine is ON. Clicking Shutdown (waiting 3.5s)...", "#ffb74d")
        cliquer_zone("btn_sub_shutdown")

        start_wait = time.time()
        while not verifier_couleur_verte("btn_sub_initialize") and time.time() - start_wait < 6:
            time.sleep(0.5)
            app.update()

        afficher_status("Machine shutdown protocol completed successfully.", "#81c784")
        return True
    else:
        afficher_status("Machine is already shut down.", "#81c784")
        return True


def quitter_application():
    arreter_machine()
    app.quit()


# ==========================================
# VERIFICATION DU NOM DE DOSSIER EN TEMPS REEL
# ==========================================
def verifier_nom_dossier_existe(event=None):
    nom_acq = entree_nom.get().strip()
    dossier_acq = os.path.join(DOSSIER_DATA_APP, nom_acq)

    if nom_acq and os.path.exists(dossier_acq):
        entree_nom.config(highlightthickness=2, highlightbackground="#f44336", highlightcolor="#f44336", bg="#3d232a")
        lbl_err_nom.config(text=f"⚠️ Folder '{nom_acq}' already exists in data_app", fg="#f44336")
        return True
    else:
        entree_nom.config(highlightthickness=1, highlightbackground="#414158", highlightcolor="#2196f3", bg="#1e1e2e")
        lbl_err_nom.config(text="", fg="#8a8a9e")
        return False


# ==========================================
# PROTOCOLE D'ACQUISITION AUTOMATIQUE
# ==========================================
def lancer_acquisition(event=None):
    nom_acq = entree_nom.get().strip()

    if not nom_acq:
        afficher_status("Error: Please enter an acquisition name.", "#e57373")
        return

    if verifier_nom_dossier_existe():
        afficher_status(f"Error: Folder '{nom_acq}' already exists. Please choose a different name.", "#e57373")
        entree_nom.focus_set()
        return

    if not charger_zones():
        afficher_status("Error: Please calibrate zones first!", "#e57373")
        return

    btn_acq.config(state=tk.DISABLED, bg="#555555")
    definir_etat_acquisition(True)

    # --- ÉTAPE 1 : Allumage / Vérification ---
    afficher_status("Step 1/6: Checking system power state...", "#e0e0e0")
    cliquer_zone("nav_init_shutdown")
    time.sleep(0.5)

    start_time = time.time()
    while not verifier_couleur_verte("nav_init_shutdown") and time.time() - start_time < 3:
        time.sleep(0.2)
        app.update()

    if not verifier_couleur_rouge("btn_sub_shutdown"):
        afficher_status("System is OFF. Clicking Initialize (waiting 3s)...", "#ffb74d")
        cliquer_zone("btn_sub_initialize")
        
        start_wait = time.time()
        while not verifier_couleur_rouge("btn_sub_shutdown") and time.time() - start_wait < 6:
            time.sleep(0.5)
            app.update()

        if not verifier_couleur_rouge("btn_sub_shutdown"):
            afficher_status("Error: System failed to initialize (Shutdown not red).", "#e57373")
            btn_acq.config(state=tk.NORMAL, bg="#4caf50")
            definir_etat_acquisition(False)
            return

    afficher_status("System is ON and ready.", "#81c784")

    # --- ÉTAPE 2 : Navigation vers Recording ---
    afficher_status("Step 2/6: Switching to Recording tab...", "#e0e0e0")
    cliquer_zone("nav_recording")
    time.sleep(0.5)

    start_time = time.time()
    while not verifier_couleur_verte("nav_recording") and time.time() - start_time < 3:
        time.sleep(0.2)
        app.update()

    # --- ÉTAPE 3 : Renseigner le nom ---
    afficher_status("Step 3/6: Setting Experiment name...", "#e0e0e0")
    saisir_texte_zone("experiment", nom_acq)
    time.sleep(0.3)

    # --- ÉTAPE 4 : Enregistrement PASSE 1 (0-180) ---
    afficher_status("Step 4/6: Config 1 (0-180) & Record...", "#e0e0e0")
    saisir_texte_zone("sample_id", "part-0-180")
    time.sleep(0.2)

    cliquer_zone("dropdown_config")
    time.sleep(0.3)
    survoler_zone("option_0_180")
    time.sleep(0.2)

    if verifier_couleur_bleue("option_0_180"):
        afficher_status("Option 0-180 highlighted in blue. Selecting...", "#81c784")
    cliquer_zone("option_0_180")
    time.sleep(0.3)

    cliquer_zone("record")
    afficher_status("Recording 1 in progress...", "#ffb74d")
    
    if not attendre_fin_enregistrement("config_area", timeout_sec=120):
        afficher_status("Error: Timeout waiting for Record 1.", "#e57373")
        btn_acq.config(state=tk.NORMAL, bg="#4caf50")
        definir_etat_acquisition(False)
        return

    # --- ÉTAPE 5 : Enregistrement PASSE 2 (180-360) ---
    afficher_status("Step 5/6: Config 2 (180-360) & Record...", "#e0e0e0")
    saisir_texte_zone("sample_id", "part-180-360")
    time.sleep(0.2)

    cliquer_zone("dropdown_config")
    time.sleep(0.3)
    survoler_zone("option_180_360")
    time.sleep(0.2)

    if verifier_couleur_bleue("option_180_360"):
        afficher_status("Option 180-360 highlighted in blue. Selecting...", "#81c784")
    cliquer_zone("option_180_360")
    time.sleep(0.3)

    cliquer_zone("record")
    afficher_status("Recording 2 in progress...", "#ffb74d")

    if not attendre_fin_enregistrement("config_area", timeout_sec=120):
        afficher_status("Error: Timeout waiting for Record 2.", "#e57373")
        btn_acq.config(state=tk.NORMAL, bg="#4caf50")
        definir_etat_acquisition(False)
        return

    afficher_status(f"Success! Acquisition '{nom_acq}' completed!", "#81c784")
    verifier_nom_dossier_existe()
    charger_fichiers_cloud_inline()

    btn_acq.config(state=tk.NORMAL, bg="#4caf50")
    definir_etat_acquisition(False)


def afficher_status(texte, couleur):
    lbl_status.config(text=texte, fg=couleur)


# ==========================================
# CLOUD TRANSFER LOGIC (DATA_APP, TRIÉ PAR DATE, COMPTEUR 72)
# ==========================================
cloud_expanded = False
dossiers_data_app = []
items_selection = {}


def compter_png_dans_dossier(folder_path):
    """Compte tous les fichiers .png présent dans le dossier et ses sous-dossiers."""
    total_png = 0
    if not os.path.exists(folder_path):
        return 0
    
    for root, _, files in os.walk(folder_path):
        for f in files:
            if f.lower().endswith(".png"):
                total_png += 1
    return total_png


def recuperer_dossiers_data_app():
    """
    Récupère tous les dossiers dans 'data_app' triés du PLUS RÉCENT au PLUS ANCIEN.
    Retourne une liste de tuples: (nom_dossier, nb_png, mtime)
    """
    liste_dossiers = []

    if not os.path.exists(DOSSIER_DATA_APP):
        return liste_dossiers

    for item in os.listdir(DOSSIER_DATA_APP):
        item_path = os.path.join(DOSSIER_DATA_APP, item)
        if os.path.isdir(item_path):
            mtime = os.path.getmtime(item_path)
            nb_png = compter_png_dans_dossier(item_path)
            liste_dossiers.append((item, nb_png, mtime))

    # Tri par date de modification décroissante (du plus récent au plus ancien)
    liste_dossiers.sort(key=lambda x: x[2], reverse=True)
    return liste_dossiers


def toggle_cloud_expansion():
    global cloud_expanded
    sw, sh = pyautogui.size()
    pos_x = sw - 700
    pos_y = 20

    if not cloud_expanded:
        app.geometry(f"675x1350+{pos_x}+{pos_y}")
        charger_fichiers_cloud_inline()
        frame_cloud_content.pack(fill=tk.BOTH, expand=True, padx=24, pady=(0, 12))
        btn_cloud.config(text="Close Cloud Transfer")
        cloud_expanded = True
    else:
        frame_cloud_content.pack_forget()
        app.geometry(f"675x900+{pos_x}+{pos_y}")
        btn_cloud.config(text="Save to Cloud")
        cloud_expanded = False


def maj_style_bouton_item(folder_name):
    if folder_name not in items_selection:
        return

    info = items_selection[folder_name]
    btn = info['button']
    is_sel = info['selected']
    count = info['png_count']

    texte_bouton = f"  [{'X' if is_sel else ' '}]  {folder_name}/  ({count}/72 png)"

    if is_sel:
        btn.config(
            text=texte_bouton,
            bg="#2e7d32", fg="#ffffff",
            activebackground="#388e3c", activeforeground="#ffffff",
            relief=tk.SOLID, bd=1, highlightbackground="#4caf50"
        )
    else:
        btn.config(
            text=texte_bouton,
            bg="#252538", fg="#78909c",
            activebackground="#2c2c42", activeforeground="#b0bec5",
            relief=tk.FLAT, bd=0
        )


def toggle_item(folder_name):
    items_selection[folder_name]['selected'] = not items_selection[folder_name]['selected']
    maj_style_bouton_item(folder_name)


def select_all_items():
    for folder_name in items_selection:
        items_selection[folder_name]['selected'] = True
        maj_style_bouton_item(folder_name)


def select_none_items():
    for folder_name in items_selection:
        items_selection[folder_name]['selected'] = False
        maj_style_bouton_item(folder_name)


def charger_fichiers_cloud_inline():
    """Rempli et met à jour l'interface des dossiers dans 'data_app'."""
    global items_selection, dossiers_data_app

    # Sauvegarder l'état des sélections actuelles
    selections_anciennes = {k: v['selected'] for k, v in items_selection.items()}
    items_selection.clear()

    for widget in scrollable_frame.winfo_children():
        widget.destroy()

    dossiers_data_app = recuperer_dossiers_data_app()

    if not dossiers_data_app:
        lbl_empty = tk.Label(
            scrollable_frame, text="No acquisitions found in data_app.",
            font=("Segoe UI", 12, "italic"), fg="#8a8a9e", bg="#1e1e2e"
        )
        lbl_empty.pack(padx=20, pady=20)
    else:
        for folder_name, nb_png, mtime in dossiers_data_app:
            # Conserver le choix si l'élément existait déjà, sinon coché par défaut
            est_selectionne = selections_anciennes.get(folder_name, True)

            items_selection[folder_name] = {
                'selected': est_selectionne,
                'png_count': nb_png,
                'button': None
            }

            btn_item = tk.Button(
                scrollable_frame, font=("Segoe UI", 13, "bold"),
                anchor="w", pady=8, cursor="hand2",
                command=lambda f=folder_name: toggle_item(f)
            )
            btn_item.pack(fill=tk.X, padx=8, pady=4)

            items_selection[folder_name]['button'] = btn_item
            maj_style_bouton_item(folder_name)


def rafraichir_automatique():
    """Mise à jour périodique toutes les 5 secondes."""
    if cloud_expanded:
        charger_fichiers_cloud_inline()
    app.after(5000, rafraichir_automatique)


def envoyer_fichiers_rclone():
    dossiers_a_envoyer = [f for f, info in items_selection.items() if info['selected']]

    if not dossiers_a_envoyer:
        lbl_transfer_status.config(text="Please select at least one folder.", fg="#e57373")
        return

    lbl_transfer_status.config(text=f"Uploading selected folders to '{RCLONE_REMOTE_PATH}'...", fg="#ffb74d")
    app.update()

    succes_count = 0
    erreurs = []

    for folder_name in dossiers_a_envoyer:
        folder_path = os.path.join(DOSSIER_DATA_APP, folder_name)
        remote_dest = f"{RCLONE_REMOTE_PATH}/{folder_name}"
        cmd = ["rclone", "copy", folder_path, remote_dest]

        try:
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode == 0:
                succes_count += 1
            else:
                erreurs.append(f"{folder_name}: {result.stderr.strip()}")
        except Exception as e:
            erreurs.append(f"{folder_name}: {str(e)}")

    if len(erreurs) == 0:
        msg_ok = f"Success! {succes_count} folder(s) uploaded to Cloud ({RCLONE_REMOTE_NAME})."
        lbl_transfer_status.config(text=msg_ok, fg="#81c784")
        afficher_status(msg_ok, "#81c784")
    else:
        msg_err = f"Transferred: {succes_count}/{len(dossiers_a_envoyer)}. Errors occurred."
        lbl_transfer_status.config(text=msg_err, fg="#e57373")
        afficher_status(f"Rclone error: {erreurs[0]}", "#e57373")


# ==========================================
# MAIN CONTROL WINDOW (675x900)
# ==========================================
app = tk.Tk()
app.title("Acquisition Control")

app.geometry("675x900")
app.configure(bg="#1e1e2e")

sw, sh = pyautogui.size()
pos_x = sw - 700
pos_y = 20
app.geometry(f"+{pos_x}+{pos_y}")
app.attributes('-topmost', True)

app.protocol("WM_DELETE_WINDOW", quitter_application)

lbl_etat = tk.Label(
    app, text="STANDBY / READY",
    font=("Segoe UI", 16, "bold"), bg="#4caf50", fg="white",
    pady=14, padx=20, bd=0
)
lbl_etat.pack(fill=tk.X, padx=30, pady=(20, 10))

# --- CARD 1: CONFIGURATION & TOOLS ---
card_tools = tk.Frame(app, bg="#2b2b3d", bd=0)
card_tools.pack(fill=tk.X, padx=30, pady=6, ipady=8)

lbl_card1 = tk.Label(
    card_tools, text="APPLICATION & TOOLS",
    font=("Segoe UI", 12, "bold"), fg="#8a8a9e", bg="#2b2b3d"
)
lbl_card1.pack(anchor=tk.W, padx=24, pady=(10, 6))

btn_frame = tk.Frame(card_tools, bg="#2b2b3d")
btn_frame.pack(fill=tk.X, padx=24, pady=5)

btn_app = tk.Button(
    btn_frame, text="Web App", command=ouvrir_application_web,
    font=("Segoe UI", 12, "bold"), bg="#3a3a52", fg="white", activebackground="#4a4a68",
    activeforeground="white", bd=0, pady=12, cursor="hand2"
)
btn_app.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 6))

btn_calib = tk.Button(
    btn_frame, text="Calibration", command=ouvrir_calibration,
    font=("Segoe UI", 12, "bold"), bg="#2196f3", fg="white", activebackground="#1e88e5",
    activeforeground="white", bd=0, pady=12, cursor="hand2"
)
btn_calib.pack(side=tk.RIGHT, fill=tk.X, expand=True, padx=(6, 0))


# --- CARD 2: NEW ACQUISITION ---
card_acq = tk.Frame(app, bg="#2b2b3d", bd=0)
card_acq.pack(fill=tk.X, padx=30, pady=6, ipady=8)

lbl_card2 = tk.Label(
    card_acq, text="NEW ACQUISITION",
    font=("Segoe UI", 12, "bold"), fg="#8a8a9e", bg="#2b2b3d"
)
lbl_card2.pack(anchor=tk.W, padx=24, pady=(10, 6))

lbl_saisie = tk.Label(
    card_acq, text="Acquisition Folder Name:",
    font=("Segoe UI", 13), fg="#e0e0e0", bg="#2b2b3d"
)
lbl_saisie.pack(anchor=tk.W, padx=24, pady=(2, 2))

entree_nom = tk.Entry(
    card_acq, font=("Segoe UI", 16), bg="#1e1e2e", fg="white",
    insertbackground="white", bd=1, relief=tk.SOLID,
    highlightthickness=1, highlightbackground="#414158", highlightcolor="#2196f3"
)
entree_nom.pack(fill=tk.X, padx=24, pady=(4, 2), ipady=6)
entree_nom.bind('<KeyRelease>', verifier_nom_dossier_existe)
entree_nom.bind('<Return>', lancer_acquisition)

lbl_err_nom = tk.Label(
    card_acq, text="", font=("Segoe UI", 10, "italic"),
    fg="#f44336", bg="#2b2b3d", anchor="w"
)
lbl_err_nom.pack(fill=tk.X, padx=24, pady=(0, 4))

btn_acq = tk.Button(
    card_acq, text="Start Acquisition", command=lancer_acquisition,
    font=("Segoe UI", 15, "bold"), bg="#4caf50", fg="white", activebackground="#43a047",
    activeforeground="white", bd=0, pady=14, cursor="hand2"
)
btn_acq.pack(fill=tk.X, padx=24, pady=(6, 14))


# --- CARD 3: CLOUD TRANSFER ---
card_cloud = tk.Frame(app, bg="#2b2b3d", bd=0)
card_cloud.pack(fill=tk.X, padx=30, pady=6, ipady=8)

lbl_card3 = tk.Label(
    card_cloud, text="CLOUD TRANSFER",
    font=("Segoe UI", 12, "bold"), fg="#8a8a9e", bg="#2b2b3d"
)
lbl_card3.pack(anchor=tk.W, padx=24, pady=(10, 6))

btn_cloud = tk.Button(
    card_cloud, text="Save to Cloud", command=toggle_cloud_expansion,
    font=("Segoe UI", 14, "bold"), bg="#9c27b0", fg="white", activebackground="#8e24aa",
    activeforeground="white", bd=0, pady=12, cursor="hand2"
)
btn_cloud.pack(fill=tk.X, padx=24, pady=(6, 10))

frame_cloud_content = tk.Frame(card_cloud, bg="#2b2b3d")

frame_select_bar = tk.Frame(frame_cloud_content, bg="#2b2b3d")
frame_select_bar.pack(fill=tk.X, pady=(4, 8))

btn_all = tk.Button(
    frame_select_bar, text="[X] Check All", command=select_all_items,
    font=("Segoe UI", 14, "bold"), bg="#3a3a52", fg="#e0e0e0",
    activebackground="#4a4a68", activeforeground="white", bd=0, pady=8, cursor="hand2"
)
btn_all.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5))

btn_none = tk.Button(
    frame_select_bar, text="[ ] Check None", command=select_none_items,
    font=("Segoe UI", 14, "bold"), bg="#3a3a52", fg="#e0e0e0",
    activebackground="#4a4a68", activeforeground="white", bd=0, pady=8, cursor="hand2"
)
btn_none.pack(side=tk.RIGHT, fill=tk.X, expand=True, padx=(5, 0))

frame_scroll_box = tk.Frame(frame_cloud_content, bg="#1e1e2e", height=220)
frame_scroll_box.pack(fill=tk.X, pady=6)
frame_scroll_box.pack_propagate(False)

canvas_scroll = tk.Canvas(frame_scroll_box, bg="#1e1e2e", highlightthickness=0)
scrollbar = tk.Scrollbar(frame_scroll_box, orient="vertical", command=canvas_scroll.yview)
scrollable_frame = tk.Frame(canvas_scroll, bg="#1e1e2e")

scrollable_frame.bind(
    "<Configure>",
    lambda e: canvas_scroll.configure(scrollregion=canvas_scroll.bbox("all"))
)

canvas_scroll.create_window((0, 0), window=scrollable_frame, anchor="nw")
canvas_scroll.configure(yscrollcommand=scrollbar.set)

canvas_scroll.pack(side="left", fill="both", expand=True, padx=8, pady=8)
scrollbar.pack(side="right", fill="y", pady=8)

lbl_transfer_status = tk.Label(
    frame_cloud_content, text="", font=("Segoe UI", 14, "italic"),
    fg="#81c784", bg="#2b2b3d"
)
lbl_transfer_status.pack(pady=4)

btn_rclone_upload = tk.Button(
    frame_cloud_content, text="Upload Selected via Rclone", command=envoyer_fichiers_rclone,
    font=("Segoe UI", 13, "bold"), bg="#4caf50", fg="white",
    activebackground="#43a047", activeforeground="white", bd=0, pady=12, cursor="hand2"
)
btn_rclone_upload.pack(fill=tk.X, pady=(4, 10))


# --- STATUS AREA ---
lbl_status = tk.Label(
    app, text="", font=("Segoe UI", 12, "italic"),
    fg="#e0e0e0", bg="#1e1e2e", wraplength=580, justify=tk.CENTER
)
lbl_status.pack(fill=tk.X, padx=30, pady=10)


# --- FOOTER ---
footer_frame = tk.Frame(app, bg="#1e1e2e")
footer_frame.pack(side=tk.BOTTOM, fill=tk.X, padx=30, pady=(10, 20))

btn_shutdown_machine = tk.Button(
    footer_frame, text="SHUTDOWN MACHINE", command=arreter_machine,
    font=("Segoe UI", 13, "bold"), bg="#ff9800", fg="black",
    activebackground="#f57c00", activeforeground="black", bd=0, pady=14, cursor="hand2"
)
btn_shutdown_machine.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 6))

btn_quitter = tk.Button(
    footer_frame, text="EXIT APPLICATION", command=quitter_application,
    font=("Segoe UI", 13, "bold"), bg="#d32f2f", fg="white",
    activebackground="#b71c1c", activeforeground="white", bd=0, pady=14, cursor="hand2"
)
btn_quitter.pack(side=tk.RIGHT, fill=tk.X, expand=True, padx=(6, 0))

# Lancement du rafraîchissement automatique à 5 secondes
app.after(5000, rafraichir_automatique)

app.mainloop()