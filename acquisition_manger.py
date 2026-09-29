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
DOSSIER_SAUVEGARDE = os.path.join(BASE_DIR, "data")

FICHIER_WEB = "index.html"
FICHIER_CALIBRATION = os.path.join(BASE_DIR, "calibration_zones.json")

# Configuration Rclone (Remote: "geneva")
RCLONE_REMOTE_NAME = "geneva"
RCLONE_REMOTE_FOLDER = "Acquisitions"  # Dossier cible sur le cloud
RCLONE_REMOTE_PATH = f"{RCLONE_REMOTE_NAME}:{RCLONE_REMOTE_FOLDER}"

# 5 Zones
ZONES_CONFIG = [
    {"id": "experiment", "label": "Experiment", "color": "#FF5722"},
    {"id": "initialize", "label": "Initialize", "color": "#2196F3"},
    {"id": "record", "label": "Record", "color": "#4CAF50"},
    {"id": "recording", "label": "Recording", "color": "#E91E63"},
    {"id": "sample_id", "label": "Sample ID", "color": "#FFC107"}
]

if not os.path.exists(DOSSIER_SAUVEGARDE):
    os.makedirs(DOSSIER_SAUVEGARDE)


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
# CALIBRATION EDITOR (Static Panel on the Right)
# ==========================================
class EditeurCalibration(tk.Toplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.parent = parent
        self.attributes("-fullscreen", True)
        self.attributes("-topmost", True)
        self.title("Calibration Editor")

        self.screen_w, self.screen_h = pyautogui.size()

        # Real Screenshot Background
        screenshot = pyautogui.screenshot()
        self.bg_image = ImageTk.PhotoImage(screenshot)

        self.canvas = tk.Canvas(self, highlightthickness=0, bg="#1e1e2e")
        self.canvas.pack(fill=tk.BOTH, expand=True)
        self.canvas.create_image(0, 0, image=self.bg_image, anchor=tk.NW)

        # Dark Overlay
        overlay = Image.new('RGBA', (self.screen_w, self.screen_h), (18, 18, 30, 110))
        self.overlay_img = ImageTk.PhotoImage(overlay)
        self.canvas.create_image(0, 0, image=self.overlay_img, anchor=tk.NW)

        self.rects_data = charger_zones()
        self.items = {}
        self.active_item = None
        self.mode = None
        self.drag_start = (0, 0)

        # Draw unified right panel onto canvas
        self._dessiner_panneau_droite()
        self._initialiser_rectangles()

        self.canvas.bind("<ButtonPress-1>", self.on_press)
        self.canvas.bind("<B1-Motion>", self.on_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_release)
        self.bind("<Return>", lambda e: self.valider())
        self.bind("<Escape>", lambda e: self.annuler())

    def _dessiner_panneau_droite(self):
        x1 = self.screen_w - 700
        y1 = 20
        x2 = x1 + 675
        y2 = y1 + 860

        # Main Panel Container
        self.canvas.create_rectangle(
            x1, y1, x2, y2, fill="#1e1e2e", outline="#2b2b3d", width=3
        )

        # 1. Header Badge: CALIBRATION MODE
        self.canvas.create_rectangle(
            x1 + 30, y1 + 30, x2 - 30, y1 + 90,
            fill="#2196f3", outline="", width=0
        )
        self.canvas.create_text(
            (x1 + x2) // 2, y1 + 60,
            text="CALIBRATION MODE", fill="white", font=("Segoe UI", 16, "bold")
        )

        # 2. Card: Zone Color Legend
        card_y1 = y1 + 110
        card_y2 = card_y1 + 430
        self.canvas.create_rectangle(
            x1 + 30, card_y1, x2 - 30, card_y2,
            fill="#2b2b3d", outline="", width=0
        )
        self.canvas.create_text(
            x1 + 54, card_y1 + 30, text="ZONE COLOR LEGEND", anchor=tk.W,
            fill="#8a8a9e", font=("Segoe UI", 13, "bold")
        )

        for idx, z in enumerate(ZONES_CONFIG):
            item_y = card_y1 + 75 + idx * 68
            # Color Box
            self.canvas.create_rectangle(
                x1 + 54, item_y, x1 + 114, item_y + 40,
                fill=z["color"], outline="", width=0
            )
            # Label
            self.canvas.create_text(
                x1 + 134, item_y + 20, text=z["label"], anchor=tk.W,
                fill="#e0e0e0", font=("Segoe UI", 14, "bold")
            )

        # 3. Save Button (Green)
        btn_save_y1 = card_y2 + 25
        btn_save_y2 = btn_save_y1 + 75
        self.btn_save_coords = (x1 + 30, btn_save_y1, x2 - 30, btn_save_y2)
        self.canvas.create_rectangle(
            self.btn_save_coords[0], self.btn_save_coords[1],
            self.btn_save_coords[2], self.btn_save_coords[3],
            fill="#4caf50", outline="", width=0
        )
        self.canvas.create_text(
            (self.btn_save_coords[0] + self.btn_save_coords[2]) // 2,
            (self.btn_save_coords[1] + self.btn_save_coords[3]) // 2,
            text="Save Calibration (Enter)", fill="white", font=("Segoe UI", 16, "bold")
        )

        # 4. Cancel Button (Dark Grey)
        btn_cancel_y1 = btn_save_y2 + 15
        btn_cancel_y2 = btn_cancel_y1 + 65
        self.btn_cancel_coords = (x1 + 30, btn_cancel_y1, x2 - 30, btn_cancel_y2)
        self.canvas.create_rectangle(
            self.btn_cancel_coords[0], self.btn_cancel_coords[1],
            self.btn_cancel_coords[2], self.btn_cancel_coords[3],
            fill="#3a3a52", outline="", width=0
        )
        self.canvas.create_text(
            (self.btn_cancel_coords[0] + self.btn_cancel_coords[2]) // 2,
            (self.btn_cancel_coords[1] + self.btn_cancel_coords[3]) // 2,
            text="Cancel (Esc)", fill="white", font=("Segoe UI", 14, "bold")
        )

    def _initialiser_rectangles(self):
        grid_cols = 3
        default_w, default_h = 240, 130

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
                x1 = 150 + col * 280
                y1 = 120 + row * 200
                x2 = x1 + default_w
                y2 = y1 + default_h

            rect_id = self.canvas.create_rectangle(
                x1, y1, x2, y2, outline=color, width=5, fill=color, stipple="gray25"
            )
            text_id = self.canvas.create_text(
                (x1 + x2) // 2, (y1 + y2) // 2, text=z["label"],
                fill="white", font=("Segoe UI", 16, "bold")
            )
            handle_id = self.canvas.create_rectangle(
                x2 - 20, y2 - 20, x2, y2, fill="white", outline=color, width=3
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
            new_x2 = max(rx1 + 50, rx2 + dx)
            new_y2 = max(ry1 + 50, ry2 + dy)
            self.canvas.coords(item["rect"], rx1, ry1, new_x2, new_y2)
            self.canvas.coords(item["text"], (rx1 + new_x2) // 2, (ry1 + new_y2) // 2)
            self.canvas.coords(item["handle"], new_x2 - 20, new_y2 - 20, new_x2, new_y2)

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
# AUTOMATION FUNCTIONS
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


def verifier_couleur_orange(zone_id):
    coords = get_coords_zone(zone_id)
    if not coords:
        return False
    _, _, x1, y1, x2, y2 = coords

    screenshot = pyautogui.screenshot(region=(x1, y1, x2 - x1, y2 - y1))
    img_np = np.array(screenshot)

    masque = (img_np[:, :, 0] > 200) & (img_np[:, :, 1] > 100) & (img_np[:, :, 1] < 180) & (img_np[:, :, 2] < 50)
    return np.sum(masque) > 20


def verifier_bouton_vert(zone_id):
    coords = get_coords_zone(zone_id)
    if not coords:
        return False
    _, _, x1, y1, x2, y2 = coords

    screenshot = pyautogui.screenshot(region=(x1, y1, x2 - x1, y2 - y1))
    img_np = np.array(screenshot)

    masque = (img_np[:, :, 0] > 100) & (img_np[:, :, 0] < 170) & \
             (img_np[:, :, 1] > 170) & \
             (img_np[:, :, 2] < 100)
    return np.sum(masque) > 50


def attendre_retour_vert(zone_id, timeout_sec=15):
    temps_debut = time.time()
    while time.time() - temps_debut < timeout_sec:
        if verifier_bouton_vert(zone_id):
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
# ACQUISITION SEQUENCE (Folder + spec.txt)
# ==========================================
def lancer_acquisition(event=None):
    nom_acq = entree_nom.get().strip()

    if not nom_acq:
        afficher_status("Error: Please enter an acquisition name.", "#e57373")
        return

    # Check if folder already exists in ./data/
    dossier_acq = os.path.join(DOSSIER_SAUVEGARDE, nom_acq)
    if os.path.exists(dossier_acq):
        afficher_status(f"Error: Folder '{nom_acq}' already exists in ./data/.", "#e57373")
        entree_nom.focus_set()
        return

    if not charger_zones():
        afficher_status("Error: Please calibrate zones first!", "#e57373")
        return

    btn_acq.config(state=tk.DISABLED, bg="#555555")
    definir_etat_acquisition(True)

    # Step 1: Initialise
    afficher_status("Step 1/4: Clicking Initialise/Shutdown...", "#e0e0e0")
    app.update()
    cliquer_zone("initialize")
    time.sleep(0.5)

    if not verifier_couleur_orange("initialize"):
        afficher_status("Warning: Initialise zone did not turn orange.", "#ffb74d")
        app.update()
        time.sleep(1)

    # Step 2: Experiment
    afficher_status("Step 2/4: Setting 'Experiment'...", "#e0e0e0")
    app.update()
    saisir_texte_zone("experiment", nom_acq)
    time.sleep(0.5)

    # Step 3: Record 1 (part-0-180)
    afficher_status("Step 3/4: Record 1 (part-0-180)...", "#e0e0e0")
    app.update()
    saisir_texte_zone("sample_id", "part-0-180")
    time.sleep(0.3)
    cliquer_zone("record")

    afficher_status("Waiting for Record 1 completion (green status)...", "#e0e0e0")
    app.update()
    if not attendre_retour_vert("record"):
        afficher_status("Error: Timeout waiting for Record 1.", "#e57373")
        btn_acq.config(state=tk.NORMAL, bg="#4caf50")
        definir_etat_acquisition(False)
        return

    # Step 4: Record 2 (part-180-360)
    afficher_status("Step 4/4: Record 2 (part-180-360)...", "#e0e0e0")
    app.update()
    saisir_texte_zone("sample_id", "part-180-360")
    time.sleep(0.3)
    cliquer_zone("record")

    afficher_status("Waiting for Record 2 completion (green status)...", "#e0e0e0")
    app.update()
    if not attendre_retour_vert("record"):
        afficher_status("Error: Timeout waiting for Record 2.", "#e57373")
        btn_acq.config(state=tk.NORMAL, bg="#4caf50")
        definir_etat_acquisition(False)
        return

    # Final Step: Saving File in ./data/<nom_acq>/spec.txt
    afficher_status(f"Saving spec.txt in ./data/{nom_acq}/...", "#e0e0e0")
    app.update()

    try:
        os.makedirs(dossier_acq, exist_ok=True)
        fichier_spec = os.path.join(dossier_acq, "spec.txt")

        with open(fichier_spec, "w", encoding="utf-8") as f:
            f.write(f"Acquisition Name: {nom_acq}\n")
            f.write(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write("part-0-180 done\n")
            f.write("part-180-360 done\n")

        afficher_status(f"Success! Folder './data/{nom_acq}' and spec.txt created!", "#81c784")
        entree_nom.delete(0, tk.END)
    except Exception as e:
        afficher_status(f"Creation Error: {e}", "#e57373")

    btn_acq.config(state=tk.NORMAL, bg="#4caf50")
    definir_etat_acquisition(False)


def afficher_status(texte, couleur):
    lbl_status.config(text=texte, fg=couleur)


# ==========================================
# INLINE CLOUD TRANSFER EXPANSION LOGIC
# ==========================================
cloud_expanded = False
dossiers_du_jour = []
items_selection = {}

def recuperer_dossiers_du_jour():
    dossiers_aujourdhui = []
    aujourdhui = date.today()

    if not os.path.exists(DOSSIER_SAUVEGARDE):
        return dossiers_aujourdhui

    for item in os.listdir(DOSSIER_SAUVEGARDE):
        item_path = os.path.join(DOSSIER_SAUVEGARDE, item)
        if os.path.isdir(item_path):
            mtime = date.fromtimestamp(os.path.getmtime(item_path))
            if mtime == aujourdhui:
                dossiers_aujourdhui.append(item)

    return sorted(dossiers_aujourdhui)


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
    info = items_selection[folder_name]
    btn = info['button']
    is_sel = info['selected']

    if is_sel:
        btn.config(
            text=f"  [X]   {folder_name}/",
            bg="#2e7d32", fg="#ffffff",
            activebackground="#388e3c", activeforeground="#ffffff",
            relief=tk.SOLID, bd=1, highlightbackground="#4caf50"
        )
    else:
        btn.config(
            text=f"  [  ]   {folder_name}/",
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
    global items_selection, dossiers_du_jour
    items_selection.clear()

    for widget in scrollable_frame.winfo_children():
        widget.destroy()

    dossiers_du_jour = recuperer_dossiers_du_jour()

    if not dossiers_du_jour:
        lbl_empty = tk.Label(
            scrollable_frame, text="No acquisition folders recorded today.",
            font=("Segoe UI", 12, "italic"), fg="#8a8a9e", bg="#1e1e2e"
        )
        lbl_empty.pack(padx=20, pady=20)
    else:
        for folder_name in dossiers_du_jour:
            items_selection[folder_name] = {'selected': True, 'button': None}

            btn_item = tk.Button(
                scrollable_frame, font=("Segoe UI", 12, "bold"),
                anchor="w", pady=8, cursor="hand2",
                command=lambda f=folder_name: toggle_item(f)
            )
            btn_item.pack(fill=tk.X, padx=8, pady=4)

            items_selection[folder_name]['button'] = btn_item
            maj_style_bouton_item(folder_name)


def envoyer_fichiers_rclone():
    dossiers_a_envoyer = [f for f, info in items_selection.items() if info['selected']]

    if not dossiers_a_envoyer:
        lbl_transfer_status.config(text="Please select at least one folder.", fg="#e57373")
        return

    lbl_transfer_status.config(text=f"Uploading folders via rclone to '{RCLONE_REMOTE_PATH}'...", fg="#ffb74d")
    app.update()

    succes_count = 0
    erreurs = []

    for folder_name in dossiers_a_envoyer:
        folder_path = os.path.join(DOSSIER_SAUVEGARDE, folder_name)
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
        msg_ok = f"Success! {succes_count} folder(s) sent to Cloud ({RCLONE_REMOTE_NAME})."
        lbl_transfer_status.config(text=msg_ok, fg="#81c784")
        afficher_status(msg_ok, "#81c784")
    else:
        msg_err = f"Transferred: {succes_count}/{len(dossiers_a_envoyer)}. Errors encountered."
        lbl_transfer_status.config(text=msg_err, fg="#e57373")
        afficher_status(f"Rclone error during transfer: {erreurs[0]}", "#e57373")


# ==========================================
# MAIN CONTROL WINDOW (675x900)
# ==========================================
app = tk.Tk()
app.title("Acquisition Control")

app.geometry("675x900")
app.configure(bg="#1e1e2e")

# Position Top-Right
sw, sh = pyautogui.size()
pos_x = sw - 700
pos_y = 20
app.geometry(f"+{pos_x}+{pos_y}")
app.attributes('-topmost', True)

# Dynamic Status Badge
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
    insertbackground="white", bd=1, relief=tk.SOLID
)
entree_nom.pack(fill=tk.X, padx=24, pady=6, ipady=6)
entree_nom.bind('<Return>', lancer_acquisition)

btn_acq = tk.Button(
    card_acq, text="Start Acquisition", command=lancer_acquisition,
    font=("Segoe UI", 15, "bold"), bg="#4caf50", fg="white", activebackground="#43a047",
    activeforeground="white", bd=0, pady=14, cursor="hand2"
)
btn_acq.pack(fill=tk.X, padx=24, pady=(10, 14))


# --- CARD 3: CLOUD TRANSFER (EXPANDABLE) ---
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

# Hidden Expandable Content Frame inside Card 3
frame_cloud_content = tk.Frame(card_cloud, bg="#2b2b3d")

# Check All / Check None Quick Selection Bar
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

# Scrollable Container (Height = 220px)
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


# --- STATUS / CONSOLE AREA ---
lbl_status = tk.Label(
    app, text="", font=("Segoe UI", 12, "italic"),
    fg="#e0e0e0", bg="#1e1e2e", wraplength=580, justify=tk.CENTER
)
lbl_status.pack(fill=tk.X, padx=30, pady=10)


# --- FOOTER: OVERSIZED EXIT BUTTON ---
btn_quitter = tk.Button(
    app, text="EXIT APPLICATION", command=app.quit,
    font=("Segoe UI", 15, "bold"), bg="#d32f2f", fg="white",
    activebackground="#b71c1c", activeforeground="white", bd=0, pady=16, cursor="hand2"
)
btn_quitter.pack(side=tk.BOTTOM, fill=tk.X, padx=30, pady=(10, 20))

app.mainloop()