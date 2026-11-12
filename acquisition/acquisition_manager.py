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
import matplotlib.pyplot as plt

import glob

# ==========================================
# CONFIGURATION
# ==========================================

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

DOSSIER_IMAGES = r"D:\data"

DOSSIER_SAUVEGARDE = os.path.join(
    BASE_DIR,
    "data"
)

# LemnaControl executable
FICHIER_EXECUTABLE = (
    r"C:\LemnaTec\Software\LemnaControl"
    r"\LemnaControlPhenoAIxpertPro.exe"
)

# Calibration file
FICHIER_CALIBRATION = os.path.join(
    BASE_DIR,
    "calibration_zones.json"
)

# Rclone configuration
RCLONE_REMOTE_NAME = "geneva"

RCLONE_REMOTE_FOLDER = "Acquisitions"

RCLONE_REMOTE_PATH = (
    f"{RCLONE_REMOTE_NAME}:{RCLONE_REMOTE_FOLDER}"
)


# ==========================================
# ZONES
# ==========================================

ZONES_CONFIG = [

    {
        "id": "experiment",
        "label": "Experiment",
        "color": "#FF5722"
    },

    {
        "id": "allconfigs",
        "label": "All configs",
        "color": "#FF5722"
    },

    {
        "id": "system",
        "label": "System",
        "color": "#2196F3"
    },

    {
        "id": "initialise",
        "label": "Initialise",
        "color": "#9C27B0"
    },

    {
        "id": "shutdown",
        "label": "Shutdown",
        "color": "#795548"
    },

    {
        "id": "record",
        "label": "Record",
        "color": "#4CAF50"
    },

    {
        "id": "recording",
        "label": "Recording",
        "color": "#E91E63"
    },

    {
        "id": "config",
        "label": "Config",
        "color": "#00BCD4"
    },

    {
        "id": "zero_180",
        "label": "0-180",
        "color": "#3F51B5"
    },

    {
        "id": "one80_360",
        "label": "180-360",
        "color": "#673AB7"
    },

    {
        "id": "sample_id",
        "label": "Sample ID",
        "color": "#FFC107"
    }
]


if not os.path.exists(
    DOSSIER_SAUVEGARDE
):
    os.makedirs(
        DOSSIER_SAUVEGARDE
    )


# ==========================================
# GLOBAL MACHINE STATE
# ==========================================

machine_allumee = False

switch_en_cours = False

cloud_expanded = False

dossiers_du_jour = []

items_selection = {}


# ==========================================
# CLIPBOARD MANAGEMENT
# ==========================================

def copier_dans_presse_papier(
    texte
):

    try:

        import pyperclip

        pyperclip.copy(
            texte
        )

        return

    except ImportError:

        pass

    try:

        process = subprocess.Popen(
            [
                "xclip",
                "-selection",
                "clipboard"
            ],
            stdin=subprocess.PIPE
        )

        process.communicate(
            input=texte.encode(
                "utf-8"
            )
        )

        return

    except Exception:

        pass

    try:

        process = subprocess.Popen(
            [
                "xsel",
                "-b",
                "-i"
            ],
            stdin=subprocess.PIPE
        )

        process.communicate(
            input=texte.encode(
                "utf-8"
            )
        )

        return

    except Exception:

        pass


# ==========================================
# CALIBRATION SAVE / LOAD
# ==========================================

def sauvegarder_zones(
    rectangles_data
):

    with open(
        FICHIER_CALIBRATION,
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            rectangles_data,
            f,
            indent=4
        )


def charger_zones():

    if os.path.exists(
        FICHIER_CALIBRATION
    ):

        try:

            with open(
                FICHIER_CALIBRATION,
                "r",
                encoding="utf-8"
            ) as f:

                return json.load(
                    f
                )

        except Exception:

            return None

    return None


# ==========================================
# CALIBRATION EDITOR
# ==========================================

class EditeurCalibration(
    tk.Toplevel
):

    def __init__(
        self,
        parent
    ):

        super().__init__(
            parent
        )

        self.parent = parent

        self.attributes(
            "-fullscreen",
            True
        )

        self.attributes(
            "-topmost",
            True
        )

        self.title(
            "Calibration Editor"
        )

        self.screen_w, self.screen_h = (
            pyautogui.size()
        )

        # ----------------------------------
        # SCREENSHOT
        # ----------------------------------

        screenshot = pyautogui.screenshot()

        self.bg_image = ImageTk.PhotoImage(
            screenshot
        )

        self.canvas = tk.Canvas(
            self,
            highlightthickness=0,
            bg="#1e1e2e"
        )

        self.canvas.pack(
            fill=tk.BOTH,
            expand=True
        )

        self.canvas.create_image(
            0,
            0,
            image=self.bg_image,
            anchor=tk.NW
        )

        # ----------------------------------
        # DARK OVERLAY
        # ----------------------------------

        overlay = Image.new(
            "RGBA",
            (
                self.screen_w,
                self.screen_h
            ),
            (
                18,
                18,
                30,
                110
            )
        )

        self.overlay_img = ImageTk.PhotoImage(
            overlay
        )

        self.canvas.create_image(
            0,
            0,
            image=self.overlay_img,
            anchor=tk.NW
        )

        # ----------------------------------
        # DATA
        # ----------------------------------

        self.rects_data = charger_zones()

        self.items = {}

        self.active_item = None

        self.mode = None

        self.drag_start = (
            0,
            0
        )

        # ----------------------------------
        # UI
        # ----------------------------------

        self._dessiner_panneau_droite()

        self._initialiser_rectangles()

        # ----------------------------------
        # EVENTS
        # ----------------------------------

        self.canvas.bind(
            "<ButtonPress-1>",
            self.on_press
        )

        self.canvas.bind(
            "<B1-Motion>",
            self.on_drag
        )

        self.canvas.bind(
            "<ButtonRelease-1>",
            self.on_release
        )

        self.bind(
            "<Return>",
            lambda e: self.valider()
        )

        self.bind(
            "<Escape>",
            lambda e: self.annuler()
        )


    # ======================================
    # RIGHT PANEL
    # ======================================

    def _dessiner_panneau_droite(
        self
    ):

        x1 = self.screen_w - 700

        y1 = 20

        x2 = x1 + 675

        y2 = min(
            self.screen_h - 20,
            y1 + 980
        )

        # ----------------------------------
        # MAIN PANEL
        # ----------------------------------

        self.canvas.create_rectangle(
            x1,
            y1,
            x2,
            y2,
            fill="#1e1e2e",
            outline="#2b2b3d",
            width=3
        )

        # ----------------------------------
        # HEADER
        # ----------------------------------

        self.canvas.create_rectangle(
            x1 + 30,
            y1 + 30,
            x2 - 30,
            y1 + 90,
            fill="#2196f3",
            outline=""
        )

        self.canvas.create_text(
            (x1 + x2) // 2,
            y1 + 60,
            text="CALIBRATION MODE",
            fill="white",
            font=(
                "Segoe UI",
                16,
                "bold"
            )
        )

        # ----------------------------------
        # LEGEND
        # ----------------------------------

        card_y1 = y1 + 110

        legend_height = (
            75
            + len(ZONES_CONFIG) * 68
            + 25
        )

        card_y2 = (
            card_y1
            + legend_height
        )

        self.canvas.create_rectangle(
            x1 + 30,
            card_y1,
            x2 - 30,
            card_y2,
            fill="#2b2b3d",
            outline=""
        )

        self.canvas.create_text(
            x1 + 54,
            card_y1 + 30,
            text="ZONE COLOR LEGEND",
            anchor=tk.W,
            fill="#8a8a9e",
            font=(
                "Segoe UI",
                13,
                "bold"
            )
        )

        # ----------------------------------
        # ZONES
        # ----------------------------------

        for idx, z in enumerate(
            ZONES_CONFIG
        ):

            item_y = (
                card_y1
                + 75
                + idx * 68
            )

            self.canvas.create_rectangle(
                x1 + 54,
                item_y,
                x1 + 114,
                item_y + 40,
                fill=z["color"],
                outline=""
            )

            self.canvas.create_text(
                x1 + 134,
                item_y + 20,
                text=z["label"],
                anchor=tk.W,
                fill="#e0e0e0",
                font=(
                    "Segoe UI",
                    14,
                    "bold"
                )
            )

        # ----------------------------------
        # SAVE BUTTON
        # ----------------------------------

        btn_save_y1 = (
            card_y2 + 25
        )

        btn_save_y2 = (
            btn_save_y1 + 75
        )

        self.btn_save_coords = (
            x1 + 30,
            btn_save_y1,
            x2 - 30,
            btn_save_y2
        )

        self.canvas.create_rectangle(
            self.btn_save_coords[0],
            self.btn_save_coords[1],
            self.btn_save_coords[2],
            self.btn_save_coords[3],
            fill="#4caf50",
            outline=""
        )

        self.canvas.create_text(
            (
                self.btn_save_coords[0]
                + self.btn_save_coords[2]
            ) // 2,
            (
                self.btn_save_coords[1]
                + self.btn_save_coords[3]
            ) // 2,
            text="Save Calibration (Enter)",
            fill="white",
            font=(
                "Segoe UI",
                16,
                "bold"
            )
        )

        # ----------------------------------
        # CANCEL BUTTON
        # ----------------------------------

        btn_cancel_y1 = (
            btn_save_y2 + 15
        )

        btn_cancel_y2 = (
            btn_cancel_y1 + 65
        )

        self.btn_cancel_coords = (
            x1 + 30,
            btn_cancel_y1,
            x2 - 30,
            btn_cancel_y2
        )

        self.canvas.create_rectangle(
            self.btn_cancel_coords[0],
            self.btn_cancel_coords[1],
            self.btn_cancel_coords[2],
            self.btn_cancel_coords[3],
            fill="#3a3a52",
            outline=""
        )

        self.canvas.create_text(
            (
                self.btn_cancel_coords[0]
                + self.btn_cancel_coords[2]
            ) // 2,
            (
                self.btn_cancel_coords[1]
                + self.btn_cancel_coords[3]
            ) // 2,
            text="Cancel (Esc)",
            fill="white",
            font=(
                "Segoe UI",
                14,
                "bold"
            )
        )


    # ======================================
    # INITIALIZE RECTANGLES
    # ======================================

    def _initialiser_rectangles(
        self
    ):

        grid_cols = 3

        default_w = 240

        default_h = 130

        for idx, z in enumerate(
            ZONES_CONFIG
        ):

            zid = z["id"]

            color = z["color"]

            # Existing calibration
            if (
                self.rects_data
                and zid in self.rects_data
            ):

                r = self.rects_data[zid]

                x1 = int(
                    r["rx1"]
                    * self.screen_w
                )

                y1 = int(
                    r["ry1"]
                    * self.screen_h
                )

                x2 = int(
                    r["rx2"]
                    * self.screen_w
                )

                y2 = int(
                    r["ry2"]
                    * self.screen_h
                )

            # Default position
            else:

                col = (
                    idx
                    % grid_cols
                )

                row = (
                    idx
                    // grid_cols
                )

                x1 = (
                    100
                    + col * 280
                )

                y1 = (
                    100
                    + row * 180
                )

                x2 = (
                    x1
                    + default_w
                )

                y2 = (
                    y1
                    + default_h
                )

            # Rectangle
            rect_id = self.canvas.create_rectangle(
                x1,
                y1,
                x2,
                y2,
                outline=color,
                width=5,
                fill=color,
                stipple="gray25"
            )

            # Label
            text_id = self.canvas.create_text(
                (
                    x1 + x2
                ) // 2,
                (
                    y1 + y2
                ) // 2,
                text=z["label"],
                fill="white",
                font=(
                    "Segoe UI",
                    16,
                    "bold"
                )
            )

            # Resize handle
            handle_id = self.canvas.create_rectangle(
                x2 - 20,
                y2 - 20,
                x2,
                y2,
                fill="white",
                outline=color,
                width=3
            )

            self.items[zid] = {
                "rect": rect_id,
                "text": text_id,
                "handle": handle_id,
                "color": color,
                "label": z["label"]
            }


    # ======================================
    # MOUSE PRESS
    # ======================================

    def on_press(
        self,
        event
    ):

        x = event.x

        y = event.y

        # Save
        if (
            self.btn_save_coords[0]
            <= x
            <= self.btn_save_coords[2]
            and
            self.btn_save_coords[1]
            <= y
            <= self.btn_save_coords[3]
        ):

            self.valider()

            return

        # Cancel
        if (
            self.btn_cancel_coords[0]
            <= x
            <= self.btn_cancel_coords[2]
            and
            self.btn_cancel_coords[1]
            <= y
            <= self.btn_cancel_coords[3]
        ):

            self.annuler()

            return

        self.active_item = None

        self.mode = None

        # Check zones
        for zid, item in self.items.items():

            # Resize handle
            hx1, hy1, hx2, hy2 = (
                self.canvas.coords(
                    item["handle"]
                )
            )

            if (
                hx1 <= x <= hx2
                and
                hy1 <= y <= hy2
            ):

                self.active_item = zid

                self.mode = "resize"

                self.drag_start = (
                    x,
                    y
                )

                return

            # Main rectangle
            rx1, ry1, rx2, ry2 = (
                self.canvas.coords(
                    item["rect"]
                )
            )

            if (
                rx1 <= x <= rx2
                and
                ry1 <= y <= ry2
            ):

                self.active_item = zid

                self.mode = "move"

                self.drag_start = (
                    x,
                    y
                )

                return


    # ======================================
    # MOUSE DRAG
    # ======================================

    def on_drag(
        self,
        event
    ):

        if not self.active_item:

            return

        dx = (
            event.x
            - self.drag_start[0]
        )

        dy = (
            event.y
            - self.drag_start[1]
        )

        self.drag_start = (
            event.x,
            event.y
        )

        item = self.items[
            self.active_item
        ]

        rx1, ry1, rx2, ry2 = (
            self.canvas.coords(
                item["rect"]
            )
        )

        # Move
        if self.mode == "move":

            self.canvas.move(
                item["rect"],
                dx,
                dy
            )

            self.canvas.move(
                item["text"],
                dx,
                dy
            )

            self.canvas.move(
                item["handle"],
                dx,
                dy
            )

        # Resize
        elif self.mode == "resize":

            new_x2 = max(
                rx1 + 10,
                rx2 + dx
            )

            new_y2 = max(
                ry1 + 10,
                ry2 + dy
            )

            self.canvas.coords(
                item["rect"],
                rx1,
                ry1,
                new_x2,
                new_y2
            )

            self.canvas.coords(
                item["text"],
                (
                    rx1 + new_x2
                ) // 2,
                (
                    ry1 + new_y2
                ) // 2
            )

            self.canvas.coords(
                item["handle"],
                new_x2 - 20,
                new_y2 - 20,
                new_x2,
                new_y2
            )


    # ======================================
    # MOUSE RELEASE
    # ======================================

    def on_release(
        self,
        event
    ):

        self.active_item = None

        self.mode = None


    # ======================================
    # VALIDATE
    # ======================================

    def valider(
        self
    ):

        export_data = {}

        for zid, item in self.items.items():

            x1, y1, x2, y2 = (
                self.canvas.coords(
                    item["rect"]
                )
            )

            export_data[zid] = {
                "rx1": (
                    x1
                    / self.screen_w
                ),
                "ry1": (
                    y1
                    / self.screen_h
                ),
                "rx2": (
                    x2
                    / self.screen_w
                ),
                "ry2": (
                    y2
                    / self.screen_h
                )
            }

        sauvegarder_zones(
            export_data
        )

        self.destroy()

        self.parent.deiconify()

        afficher_status(
            "Calibration saved successfully!",
            "#81c784"
        )


    # ======================================
    # CANCEL
    # ======================================

    def annuler(
        self
    ):

        self.destroy()

        self.parent.deiconify()


# ==========================================
# APPLICATION LAUNCH
# ==========================================

def ouvrir_application():

    if not os.path.isfile(FICHIER_EXECUTABLE):

        afficher_status(
            "Error: Executable not found:\n"
            f"{FICHIER_EXECUTABLE}",
            "#e57373"
        )

        return

    try:

        subprocess.Popen(
            [FICHIER_EXECUTABLE],
            creationflags=(
                subprocess.DETACHED_PROCESS
                | subprocess.CREATE_NEW_PROCESS_GROUP
            ),
            close_fds=True
        )

        afficher_status(
            "LemnaControl PhenoAIxpertPro opened.",
            "#e0e0e0"
        )

    except Exception as e:

        afficher_status(
            f"Opening error: {e}",
            "#e57373"
        )

# ==========================================
# OPEN CALIBRATION
# ==========================================

def ouvrir_calibration():

    app.withdraw()

    app.after(
        200,
        lambda: EditeurCalibration(app)
    )


# ==========================================
# GET ZONE COORDINATES
# ==========================================

def get_coords_zone(
    zone_id
):

    data = charger_zones()

    if (
        not data
        or zone_id not in data
    ):

        return None

    sw, sh = pyautogui.size()

    z = data[
        zone_id
    ]

    x1 = int(
        z["rx1"] * sw
    )

    y1 = int(
        z["ry1"] * sh
    )

    x2 = int(
        z["rx2"] * sw
    )

    y2 = int(
        z["ry2"] * sh
    )

    cx = (
        x1 + x2
    ) // 2

    cy = (
        y1 + y2
    ) // 2

    return (
        cx,
        cy,
        x1,
        y1,
        x2,
        y2
    )


# ==========================================
# CLICK ZONE
# ==========================================

def cliquer_zone(
    zone_id
):

    coords = get_coords_zone(
        zone_id
    )

    if not coords:

        return (
            False,
            f"Zone '{zone_id}' not calibrated."
        )

    cx, cy, _, _, _, _ = coords

    try:

        pyautogui.click(
            cx,
            cy
        )

        return (
            True,
            (
                cx,
                cy
            )
        )

    except Exception as e:

        return (
            False,
            str(e)
        )


# ==========================================
# TYPE TEXT IN ZONE
# ==========================================

def saisir_texte_zone(
    zone_id,
    texte
):

    succes, msg = cliquer_zone(
        zone_id
    )

    if not succes:

        return (
            False,
            msg
        )

    time.sleep(
        0.2
    )

    copier_dans_presse_papier(
        texte
    )

    pyautogui.hotkey(
        "ctrl",
        "a"
    )

    time.sleep(
        0.1
    )

    pyautogui.press(
        "backspace"
    )

    time.sleep(
        0.1
    )

    pyautogui.hotkey(
        "ctrl",
        "v"
    )

    time.sleep(
        0.1
    )

    return (
        True,
        f"Text '{texte}' pasted."
    )


# ==========================================
# COLOR DETECTION
# ==========================================

def _capturer_zone_image(
    zone_id
):

    coords = get_coords_zone(
        zone_id
    )

    if not coords:

        return None

    _, _, x1, y1, x2, y2 = coords

    width = x2 - x1

    height = y2 - y1

    if width <= 0 or height <= 0:

        return None

    try:

        screenshot = pyautogui.screenshot(
            region=(
                x1,
                y1,
                width,
                height
            )
        )

        return np.array(
            screenshot
        )

    except Exception:

        return None


def verifier_bouton_vert(
    zone_id
):

    img_np = _capturer_zone_image(
        zone_id
    )

    if img_np is None:

        return False

    r = img_np[:, :, 0].astype(
        np.float32
    )

    g = img_np[:, :, 1].astype(
        np.float32
    )

    b = img_np[:, :, 2].astype(
        np.float32
    )

    masque = (
        (g > 140)
        &
        (g > r * 1.25)
        &
        (g > b * 1.25)
    )

    return (
        np.sum(masque)
        > 50
    )


def verifier_bouton_bleu(
    zone_id
):

    img_np = _capturer_zone_image(
        zone_id
    )

    if img_np is None:

        return False

    r = img_np[:, :, 0].astype(
        np.float32
    )

    g = img_np[:, :, 1].astype(
        np.float32
    )

    b = img_np[:, :, 2].astype(
        np.float32
    )

    masque = (
        (b > 120)
        &
        (b > r * 1.30)
        &
        (b > g * 1.10)
    )

    return (
        np.sum(masque)
        > 50
    )


def verifier_bouton_rouge(
    zone_id
):

    img_np = _capturer_zone_image(
        zone_id
    )

    if img_np is None:

        return False

    r = img_np[:, :, 0].astype(
        np.float32
    )

    g = img_np[:, :, 1].astype(
        np.float32
    )

    b = img_np[:, :, 2].astype(
        np.float32
    )

    masque = (
        (r > 150)
        &
        (g < 120)
        &
        (b < 120)
        &
        (r > g * 1.40)
        &
        (r > b * 1.40)
    )

    return (
        np.sum(masque)
        > 50
    )


# ==========================================
# GENERIC COLOR VERIFICATION
# ==========================================

def verifier_couleur_zone(
    zone_id,
    couleur
):

    couleur = couleur.lower()

    if couleur == "vert":

        return verifier_bouton_vert(
            zone_id
        )

    if couleur == "bleu":

        return verifier_bouton_bleu(
            zone_id
        )

    if couleur == "rouge":

        return verifier_bouton_rouge(
            zone_id
        )

    return False


# ==========================================
# GENERIC WAIT FOR COLOR
#
# IMPORTANT:
# We FIRST test the current state.
# If already correct, we immediately
# return True.
# ==========================================

def attendre_couleur_zone(
    zone_id,
    couleur,
    timeout_sec=30,
    interval_sec=0.5
):

    temps_debut = time.time()

    # --------------------------------------
    # IMMEDIATE CHECK
    # --------------------------------------

    if verifier_couleur_zone(
        zone_id,
        couleur
    ):

        return True

    # --------------------------------------
    # WAIT LOOP
    # --------------------------------------

    while (
        time.time()
        - temps_debut
        < timeout_sec
    ):

        if verifier_couleur_zone(
            zone_id,
            couleur
        ):

            return True

        time.sleep(
            interval_sec
        )

        try:

            app.update()

        except Exception:

            pass

    return False


# ==========================================
# MACHINE STATUS
# ==========================================

def definir_etat_acquisition(
    en_cours
):

    if en_cours:

        lbl_etat.config(
            text="PROCESS IN PROGRESS",
            bg="#f44336",
            fg="white"
        )

    else:

        if machine_allumee:

            lbl_etat.config(
                text="MACHINE ON / READY",
                bg="#4caf50",
                fg="white"
            )

        else:

            lbl_etat.config(
                text="MACHINE OFF / STANDBY",
                bg="#555555",
                fg="white"
            )

    app.update()


# ==========================================
# SWITCH BUTTON RESET
# ==========================================

def terminer_switch():

    global switch_en_cours

    switch_en_cours = False

    if machine_allumee:

        btn_switch.config(
            state=tk.NORMAL,
            text="SWITCH OFF",
            bg="#d32f2f",
            fg="white",
            activebackground="#b71c1c",
            activeforeground="white"
        )

    else:

        btn_switch.config(
            state=tk.NORMAL,
            text="SWITCH ON",
            bg="#555555",
            fg="white",
            activebackground="#666666",
            activeforeground="white"
        )

    definir_etat_acquisition(
        False
    )


# ==========================================
# SWITCH MACHINE ON / OFF
# ==========================================

def switch_machine():

    global machine_allumee

    global switch_en_cours

    # --------------------------------------
    # PREVENT DOUBLE CLICK
    # --------------------------------------

    if switch_en_cours:

        return

    # --------------------------------------
    # CALIBRATION REQUIRED
    # --------------------------------------

    if not charger_zones():

        afficher_status(
            "Error: Please calibrate zones first!",
            "#e57373"
        )

        return

    switch_en_cours = True

    btn_switch.config(
        state=tk.DISABLED,
        bg="#555555",
        fg="#aaaaaa"
    )

    definir_etat_acquisition(
        True
    )

    app.update()

    # ======================================
    # SWITCH ON
    # ======================================

    if not machine_allumee:

        # ----------------------------------
        # STEP 1 - SYSTEM
        # ----------------------------------

        afficher_status(
            "Power ON: Clicking System...",
            "#e0e0e0"
        )

        app.update()

        succes, msg = cliquer_zone(
            "system"
        )

        if not succes:

            afficher_status(
                f"Error clicking System: {msg}",
                "#e57373"
            )

            terminer_switch()

            return

        time.sleep(
            0.5
        )

        # ----------------------------------
        # STEP 2 - INITIALISE GREEN
        #
        # IMPORTANT:
        # If Initialise is ALREADY green,
        # we continue immediately.
        # ----------------------------------

        afficher_status(
            "Power ON: Checking Initialise "
            "for green...",
            "#e0e0e0"
        )

        app.update()

        if not attendre_couleur_zone(
            "initialise",
            "vert",
            timeout_sec=30
        ):

            afficher_status(
                "Error: Initialise did not "
                "turn green.",
                "#e57373"
            )

            terminer_switch()

            return

        # ----------------------------------
        # STEP 3 - CLICK INITIALISE
        # ----------------------------------

        afficher_status(
            "Power ON: Initialise is green. "
            "Clicking Initialise...",
            "#e0e0e0"
        )

        app.update()

        succes, msg = cliquer_zone(
            "initialise"
        )

        if not succes:

            afficher_status(
                f"Error clicking Initialise: {msg}",
                "#e57373"
            )

            terminer_switch()

            return

        time.sleep(
            0.5
        )

        # ----------------------------------
        # STEP 4 - SHUTDOWN RED
        #
        # Again, immediate check first.
        # ----------------------------------

        afficher_status(
            "Power ON: Checking Shutdown "
            "for red...",
            "#e0e0e0"
        )

        app.update()

        if not attendre_couleur_zone(
            "shutdown",
            "rouge",
            timeout_sec=30
        ):

            afficher_status(
                "Error: Shutdown did not "
                "turn red.",
                "#e57373"
            )

            terminer_switch()

            return

        # ----------------------------------
        # MACHINE IS ON
        # ----------------------------------

        machine_allumee = True

        btn_switch.config(
            state=tk.NORMAL,
            text="SWITCH OFF",
            bg="#d32f2f",
            fg="white",
            activebackground="#b71c1c",
            activeforeground="white"
        )

        afficher_status(
            "Machine is ON.",
            "#81c784"
        )

        definir_etat_acquisition(
            False
        )

        switch_en_cours = False

        return

    # ======================================
    # SWITCH OFF
    # ======================================

    else:

        # ----------------------------------
        # STEP 1 - SYSTEM
        # ----------------------------------

        afficher_status(
            "Power OFF: Clicking System...",
            "#e0e0e0"
        )

        app.update()

        succes, msg = cliquer_zone(
            "system"
        )

        if not succes:

            afficher_status(
                f"Error clicking System: {msg}",
                "#e57373"
            )

            terminer_switch()

            return

        time.sleep(
            0.5
        )

        # ----------------------------------
        # STEP 2 - SHUTDOWN RED
        #
        # Immediate check included.
        # ----------------------------------

        afficher_status(
            "Power OFF: Checking Shutdown "
            "for red...",
            "#e0e0e0"
        )

        app.update()

        if not attendre_couleur_zone(
            "shutdown",
            "rouge",
            timeout_sec=30
        ):

            afficher_status(
                "Error: Shutdown did not "
                "turn red.",
                "#e57373"
            )

            terminer_switch()

            return

        # ----------------------------------
        # STEP 3 - CLICK SHUTDOWN
        # ----------------------------------

        afficher_status(
            "Power OFF: Shutdown is red. "
            "Clicking Shutdown...",
            "#e0e0e0"
        )

        app.update()

        succes, msg = cliquer_zone(
            "shutdown"
        )

        if not succes:

            afficher_status(
                f"Error clicking Shutdown: {msg}",
                "#e57373"
            )

            terminer_switch()

            return

        time.sleep(
            0.5
        )

        # ----------------------------------
        # STEP 4 - INITIALISE GREEN
        #
        # Immediate check included.
        # ----------------------------------

        afficher_status(
            "Power OFF: Checking Initialise "
            "for green...",
            "#e0e0e0"
        )

        app.update()

        if not attendre_couleur_zone(
            "initialise",
            "vert",
            timeout_sec=30
        ):

            afficher_status(
                "Error: Initialise did not "
                "turn green.",
                "#e57373"
            )

            terminer_switch()

            return

        # ----------------------------------
        # MACHINE IS OFF
        # ----------------------------------

        machine_allumee = False

        btn_switch.config(
            state=tk.NORMAL,
            text="SWITCH ON",
            bg="#555555",
            fg="white",
            activebackground="#666666",
            activeforeground="white"
        )

        afficher_status(
            "Machine is OFF.",
            "#81c784"
        )

        definir_etat_acquisition(
            False
        )

        switch_en_cours = False


# ==========================================
# ACQUISITION ERROR RESET
# ==========================================

def erreur_acquisition(
    message
):

    afficher_status(
        message,
        "#e57373"
    )

    btn_acq.config(
        state=tk.NORMAL,
        bg="#4caf50"
    )

    definir_etat_acquisition(
        False
    )


# ==========================================
# ACQUISITION SEQUENCE
# ==========================================

def lancer_acquisition(
    event=None
):

    nom_acq = entree_nom.get().strip()

    # --------------------------------------
    # NAME CHECK
    # --------------------------------------

    if not nom_acq:

        afficher_status(
            "Error: Please enter an acquisition name.",
            "#e57373"
        )

        return

    # --------------------------------------
    # MACHINE CHECK
    # --------------------------------------

    if not machine_allumee:

        afficher_status(
            "Error: Machine is OFF. "
            "Please switch it ON first.",
            "#e57373"
        )

        return

    # --------------------------------------
    # FOLDER CHECK
    # --------------------------------------

    dossier_acq = os.path.join(
        DOSSIER_SAUVEGARDE,
        nom_acq
    )

    if os.path.exists(
        dossier_acq
    ):

        afficher_status(
            f"Error: Folder '{nom_acq}' "
            "already exists in ./data/.",
            "#e57373"
        )

        entree_nom.focus_set()

        return

    # --------------------------------------
    # CALIBRATION CHECK
    # --------------------------------------

    if not charger_zones():

        afficher_status(
            "Error: Please calibrate zones first!",
            "#e57373"
        )

        return

    # --------------------------------------
    # REQUIRED ZONES CHECK
    # --------------------------------------

    zones_requises = [
        "recording",
        "experiment",
        "config",
        "zero_180",
        "one80_360",
        "sample_id",
        "record"
    ]

    zones = charger_zones()

    zones_manquantes = [
        zone
        for zone in zones_requises
        if zone not in zones
    ]

    if zones_manquantes:

        afficher_status(
            "Error: Missing calibration zones: "
            + ", ".join(
                zones_manquantes
            ),
            "#e57373"
        )

        return

    # --------------------------------------
    # DISABLE ACQUISITION BUTTON
    # --------------------------------------

    btn_acq.config(
        state=tk.DISABLED,
        bg="#555555"
    )

    definir_etat_acquisition(
        True
    )

    # ======================================
    # STEP 1
    # RECORDING
    # ======================================

    afficher_status(
        "Step 1: Clicking Recording...",
        "#e0e0e0"
    )

    app.update()

    succes, msg = cliquer_zone(
        "recording"
    )

    if not succes:

        erreur_acquisition(
            f"Error clicking Recording: {msg}"
        )

        return

    time.sleep(
        0.3
    )

    # ======================================
    # STEP 2
    # RECORDING GREEN
    #
    # IMPORTANT:
    # If Recording is already green,
    # attendre_couleur_zone() returns
    # immediately.
    # ======================================

    afficher_status(
        "Step 2: Checking Recording is green...",
        "#e0e0e0"
    )

    app.update()

    if not attendre_couleur_zone(
        "recording",
        "vert",
        timeout_sec=30
    ):

        erreur_acquisition(
            "Error: Recording did not turn green."
        )

        return

    # ======================================
    # STEP 3
    # EXPERIMENT
    # ======================================

    afficher_status(
        "Step 3: Setting Experiment...",
        "#e0e0e0"
    )

    app.update()

    succes, msg = saisir_texte_zone(
        "experiment",
        nom_acq
    )

    if not succes:

        erreur_acquisition(
            f"Error setting Experiment: {msg}"
        )

        return

    time.sleep(
        0.3
    )

    # ======================================
    # STEP 4
    # CONFIG
    # ======================================

    afficher_status(
        "Step 4: Clicking Config...",
        "#e0e0e0"
    )

    app.update()

    succes, msg = cliquer_zone(
        "config"
    )

    if not succes:

        erreur_acquisition(
            f"Error clicking Config: {msg}"
        )

        return

    time.sleep(
        0.5
    )

    # ======================================
    # STEP 5
    # POSITION 0-180
    # ======================================

    afficher_status(
        "Step 5: Checking 0-180 is blue...",
        "#e0e0e0"
    )

    app.update()

    if not attendre_couleur_zone(
        "zero_180",
        "bleu",
        timeout_sec=30
    ):

        erreur_acquisition(
            "Error: 0-180 did not turn blue."
        )

        return

    # ======================================
    # STEP 6
    # CLICK 0-180
    # ======================================

    afficher_status(
        "Step 6: 0-180 is blue. Clicking it...",
        "#e0e0e0"
    )

    app.update()

    succes, msg = cliquer_zone(
        "zero_180"
    )

    if not succes:

        erreur_acquisition(
            f"Error clicking 0-180: {msg}"
        )

        return

    time.sleep(
        0.5
    )

    # ======================================
    # STEP 7
    # SAMPLE ID 0-180
    # ======================================

    afficher_status(
        "Step 7: Setting Sample ID "
        "'part-0-180'...",
        "#e0e0e0"
    )

    app.update()

    succes, msg = saisir_texte_zone(
        "sample_id",
        "part-0-180"
    )

    if not succes:

        erreur_acquisition(
            f"Error setting Sample ID: {msg}"
        )

        return

    time.sleep(
        0.3
    )

    # ======================================
    # STEP 8
    # RECORD F1 - PASS 1
    # ======================================

    afficher_status(
        "Step 8: Starting Record F1 "
        "for 0-180...",
        "#e0e0e0"
    )

    app.update()

    succes, msg = cliquer_zone(
        "record"
    )

    if not succes:

        erreur_acquisition(
            f"Error clicking Record F1: {msg}"
        )

        return

    # ======================================
    # STEP 9
    # WAIT RECORD GREEN - PASS 1
    # ======================================

    afficher_status(
        "Step 9: Waiting for Record F1 "
        "to become green...",
        "#e0e0e0"
    )

    app.update()

    if not attendre_couleur_zone(
        "allconfigs",
        "vert",
        timeout_sec=600
    ):

        erreur_acquisition(
            "Error: Record F1 did not "
            "finish / turn green."
        )

        return

    # ======================================
    # STEP 10
    # POSITION 180-360
    # ======================================

    afficher_status(
        "Step 4: Clicking Config...",
        "#e0e0e0"
    )

    app.update()

    succes, msg = cliquer_zone(
        "config"
    )

    if not succes:

        erreur_acquisition(
            f"Error clicking Config: {msg}"
        )

        return

    time.sleep(
        0.5
    )


    afficher_status(
        "Step 10: Checking 180-360 "
        "is blue...",
        "#e0e0e0"
    )

    app.update()

    if not attendre_couleur_zone(
        "one80_360",
        "bleu",
        timeout_sec=30
    ):

        erreur_acquisition(
            "Error: 180-360 did not "
            "turn blue."
        )

        return

    # ======================================
    # STEP 11
    # CLICK 180-360
    # ======================================

    afficher_status(
        "Step 11: 180-360 is blue. "
        "Clicking it...",
        "#e0e0e0"
    )

    app.update()

    succes, msg = cliquer_zone(
        "one80_360"
    )

    if not succes:

        erreur_acquisition(
            f"Error clicking 180-360: {msg}"
        )

        return

    time.sleep(
        0.5
    )

    # ======================================
    # STEP 12
    # SAMPLE ID 180-360
    # ======================================

    afficher_status(
        "Step 12: Setting Sample ID "
        "'part-180-360'...",
        "#e0e0e0"
    )

    app.update()

    succes, msg = saisir_texte_zone(
        "sample_id",
        "part-180-360"
    )

    if not succes:

        erreur_acquisition(
            f"Error setting Sample ID: {msg}"
        )

        return

    time.sleep(
        0.3
    )

    # ======================================
    # STEP 13
    # RECORD F1 - PASS 2
    # ======================================

    afficher_status(
        "Step 13: Starting Record F1 "
        "for 180-360...",
        "#e0e0e0"
    )

    app.update()

    succes, msg = cliquer_zone(
        "record"
    )

    if not succes:

        erreur_acquisition(
            f"Error clicking Record F1: {msg}"
        )

        return

    # ======================================
    # STEP 14
    # WAIT RECORD GREEN - PASS 2
    # ======================================

    afficher_status(
        "Step 14: Waiting for Record F1 "
        "to become green...",
        "#e0e0e0"
    )

    app.update()

    if not attendre_couleur_zone(
        "allconfigs",
        "vert",
        timeout_sec=600
    ):

        erreur_acquisition(
            "Error: Record F1 did not "
            "finish / turn green."
        )

        return

    # ======================================
    # STEP 15
    # SAVE SPEC.TXT
    # ======================================

    afficher_status(
        f"Step 15: Saving spec.txt "
        f"in ./data/{nom_acq}/...",
        "#e0e0e0"
    )

    app.update()

    try:

        os.makedirs(
            dossier_acq,
            exist_ok=True
        )

        fichier_spec = os.path.join(
            dossier_acq,
            "spec.txt"
        )

        with open(
            fichier_spec,
            "w",
            encoding="utf-8"
        ) as f:

            f.write(
                f"Acquisition Name: {nom_acq}\n"
            )

            f.write(
                "Timestamp: "
                f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
            )

            f.write(
                "part-0-180 done\n"
            )

            f.write(
                "part-180-360 done\n"
            )

        afficher_status(
            f"Success! Folder './data/{nom_acq}' "
            "and spec.txt created!",
            "#81c784"
        )

        entree_nom.delete(
            0,
            tk.END
        )

    except Exception as e:

        afficher_status(
            f"Creation Error: {e}",
            "#e57373"
        )

    # --------------------------------------
    # RESTORE BUTTON
    # --------------------------------------

    btn_acq.config(
        state=tk.NORMAL,
        bg="#4caf50"
    )

    definir_etat_acquisition(
        False
    )


# ==========================================
# STATUS
# ==========================================

def afficher_status(
    texte,
    couleur
):

    lbl_status.config(
        text=texte,
        fg=couleur
    )

    app.update()


# ==========================================
# CLOUD
# ==========================================

def recuperer_dossiers_du_jour():

    dossiers_aujourdhui = []

    aujourdhui = date.today()

    if not os.path.exists(
        DOSSIER_SAUVEGARDE
    ):

        return dossiers_aujourdhui

    for item in os.listdir(
        DOSSIER_SAUVEGARDE
    ):

        item_path = os.path.join(
            DOSSIER_SAUVEGARDE,
            item
        )

        if os.path.isdir(
            item_path
        ):

            mtime = date.fromtimestamp(
                os.path.getmtime(
                    item_path
                )
            )

            if mtime == aujourdhui:

                dossiers_aujourdhui.append(
                    item
                )

    return sorted(
        dossiers_aujourdhui
    )


# ==========================================
# CLOUD EXPANSION
# ==========================================

def toggle_cloud_expansion():

    global cloud_expanded

    if not cloud_expanded:

        app.geometry(
            f"{BASE_WIDTH}x"
            f"{EXPANDED_HEIGHT}+"
            f"{POS_X}+{POS_Y}"
        )

        charger_fichiers_cloud_inline()

        frame_cloud_content.pack(
            fill=tk.BOTH,
            expand=True,
            padx=P(24),
            pady=(
                0,
                P(12)
            )
        )

        btn_cloud.config(
            text="Close Cloud Transfer"
        )

        cloud_expanded = True

    else:

        frame_cloud_content.pack_forget()

        app.geometry(
            f"{BASE_WIDTH}x"
            f"{BASE_HEIGHT}+"
            f"{POS_X}+{POS_Y}"
        )

        btn_cloud.config(
            text="Save to Cloud"
        )

        cloud_expanded = False


# ==========================================
# CLOUD ITEM SELECTION
# ==========================================

def toggle_item(
    folder_name
):

    items_selection[
        folder_name
    ]["selected"] = not items_selection[
        folder_name
    ]["selected"]

    maj_style_bouton_item(
        folder_name
    )


def select_all_items():

    for folder_name in items_selection:

        items_selection[
            folder_name
        ]["selected"] = True

        maj_style_bouton_item(
            folder_name
        )


def select_none_items():

    for folder_name in items_selection:

        items_selection[
            folder_name
        ]["selected"] = False

        maj_style_bouton_item(
            folder_name
        )



# ==========================================
# CLOUD ITEM STYLE
# ==========================================

def actualiser_compteurs_png():

    for folder_name in list(items_selection.keys()):

        info = items_selection.get(
            folder_name
        )

        if info and info.get("button"):

            maj_style_bouton_item(
                folder_name
            )

    # Re-run every 5 seconds
    app.after(
        5000,
        actualiser_compteurs_png
    )

def maj_style_bouton_item(folder_name):

    info = items_selection[
        folder_name
    ]

    btn = info[
        "button"
    ]

    is_sel = info[
        "selected"
    ]

    # --------------------------------------
    # COUNT PNG
    # --------------------------------------

    nb_images = compter_images_png(
        folder_name
    )

    # --------------------------------------
    # BUTTON TEXT
    # --------------------------------------

    if is_sel:

        btn.config(
            text=(
                f"  [X]   {folder_name}/"
                f"    ({nb_images} PNG)"
            ),
            bg="#2e7d32",
            fg="#ffffff",
            activebackground="#388e3c",
            activeforeground="#ffffff",
            relief=tk.SOLID,
            bd=max(
                1,
                P(1)
            ),
            highlightbackground="#4caf50"
        )

    else:

        btn.config(
            text=(
                f"  [  ]   {folder_name}/"
                f"    ({nb_images} PNG)"
            ),
            bg="#252538",
            fg="#78909c",
            activebackground="#2c2c42",
            activeforeground="#b0bec5",
            relief=tk.FLAT,
            bd=0
        )



# ==========================================
# LOAD CLOUD FOLDERS
# ==========================================

def compter_images_png(folder_name):

    pattern = os.path.join(
        DOSSIER_IMAGES,
        folder_name,
        "*",
        "*.png"
    )

    try:

        fichiers_png = glob.glob(
            pattern
        )

        return len(
            fichiers_png
        )

    except Exception:
        return 0

def charger_fichiers_cloud_inline():

    global items_selection

    global dossiers_du_jour

    items_selection.clear()

    for widget in (
        scrollable_frame.winfo_children()
    ):

        widget.destroy()

    dossiers_du_jour = (
        recuperer_dossiers_du_jour()
    )

    if not dossiers_du_jour:

        lbl_empty = tk.Label(
            scrollable_frame,
            text=(
                "No acquisition folders "
                "recorded today."
            ),
            font=(
                "Segoe UI",
                F(12),
                "italic"
            ),
            fg="#8a8a9e",
            bg="#1e1e2e"
        )

        lbl_empty.pack(
            padx=P(20),
            pady=P(20)
        )

    else:

        for folder_name in (
            dossiers_du_jour
        ):

            items_selection[
                folder_name
            ] = {
                "selected": True,
                "button": None
            }

            btn_item = tk.Button(
                scrollable_frame,
                font=(
                    "Segoe UI",
                    F(12),
                    "bold"
                ),
                anchor="w",
                pady=P(8),
                cursor="hand2",
                command=lambda f=folder_name:
                    toggle_item(f)
            )

            btn_item.pack(
                fill=tk.X,
                padx=P(8),
                pady=P(4)
            )

            items_selection[
                folder_name
            ]["button"] = btn_item

            maj_style_bouton_item(
                folder_name
            )


# ==========================================
# RCLONE UPLOAD
# ==========================================

def envoyer_fichiers_rclone():

    dossiers_a_envoyer = [
        f
        for f, info
        in items_selection.items()
        if info["selected"]
    ]

    if not dossiers_a_envoyer:

        lbl_transfer_status.config(
            text=(
                "Please select at least one folder."
            ),
            fg="#e57373"
        )

        return

    lbl_transfer_status.config(
        text=(
            "Uploading folders via rclone "
            f"to '{RCLONE_REMOTE_PATH}'..."
        ),
        fg="#ffb74d"
    )

    app.update()

    succes_count = 0

    erreurs = []

    for folder_name in (
        dossiers_a_envoyer
    ):

        folder_path = os.path.join(
            DOSSIER_SAUVEGARDE,
            folder_name
        )

        remote_dest = (
            f"{RCLONE_REMOTE_PATH}/"
            f"{folder_name}"
        )

        cmd = [
            "rclone",
            "copy",
            folder_path,
            remote_dest
        ]

        try:

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True
            )

            if result.returncode == 0:

                succes_count += 1

            else:

                erreurs.append(
                    f"{folder_name}: "
                    f"{result.stderr.strip()}"
                )

        except Exception as e:

            erreurs.append(
                f"{folder_name}: {str(e)}"
            )

    if len(erreurs) == 0:

        msg_ok = (
            f"Success! {succes_count} "
            "folder(s) sent to Cloud "
            f"({RCLONE_REMOTE_NAME})."
        )

        lbl_transfer_status.config(
            text=msg_ok,
            fg="#81c784"
        )

        afficher_status(
            msg_ok,
            "#81c784"
        )

    else:

        msg_err = (
            f"Transferred: "
            f"{succes_count}/"
            f"{len(dossiers_a_envoyer)}. "
            "Errors encountered."
        )

        lbl_transfer_status.config(
            text=msg_err,
            fg="#e57373"
        )

        afficher_status(
            "Rclone error during transfer: "
            f"{erreurs[0]}",
            "#e57373"
        )


# ==========================================
# MAIN CONTROL WINDOW
# ==========================================

app = tk.Tk()

app.title(
    "Acquisition Control"
)


# ==========================================
# RESPONSIVE DIMENSIONS
# ==========================================

sw = app.winfo_screenwidth()

sh = app.winfo_screenheight()

BASE_HEIGHT = int(
    sh * 0.5
)

SCALE = (
    BASE_HEIGHT
    / 900.0
)

BASE_WIDTH = int(
    675 * SCALE
)

EXPANDED_HEIGHT = int(
    1350 * SCALE
)

POS_X = (
    sw
    - BASE_WIDTH
    - 25
)

POS_Y = 20

app.geometry(
    f"{BASE_WIDTH}x"
    f"{BASE_HEIGHT}+"
    f"{POS_X}+{POS_Y}"
)

app.configure(
    bg="#1e1e2e"
)

app.attributes(
    "-topmost",
    True
)


# ==========================================
# RESPONSIVE FONT
# ==========================================

def F(
    size
):

    return max(
        8,
        int(
            size * SCALE
        )
    )


def P(
    size
):

    return int(
        size * SCALE
    )


# ==========================================
# GLOBAL STATUS
# ==========================================

lbl_etat = tk.Label(
    app,
    text="MACHINE OFF / STANDBY",
    font=(
        "Segoe UI",
        F(16),
        "bold"
    ),
    bg="#555555",
    fg="white",
    pady=P(14),
    padx=P(20),
    bd=0
)

lbl_etat.pack(
    fill=tk.X,
    padx=P(30),
    pady=(
        P(20),
        P(10)
    )
)


# ==========================================
# CARD 1 - APPLICATION & TOOLS
# ==========================================

card_tools = tk.Frame(
    app,
    bg="#2b2b3d",
    bd=0
)

card_tools.pack(
    fill=tk.X,
    padx=P(30),
    pady=P(6),
    ipady=P(8)
)

lbl_card1 = tk.Label(
    card_tools,
    text="APPLICATION & TOOLS",
    font=(
        "Segoe UI",
        F(12),
        "bold"
    ),
    fg="#8a8a9e",
    bg="#2b2b3d"
)

lbl_card1.pack(
    anchor=tk.W,
    padx=P(24),
    pady=(
        P(10),
        P(6)
    )
)


# ==========================================
# APPLICATION BUTTONS
# ==========================================

btn_frame = tk.Frame(
    card_tools,
    bg="#2b2b3d"
)

btn_frame.pack(
    fill=tk.X,
    padx=P(24),
    pady=P(5)
)


btn_app = tk.Button(
    btn_frame,
    text="Launch LemnaControl",
    command=ouvrir_application,
    font=(
        "Segoe UI",
        F(12),
        "bold"
    ),
    bg="#3a3a52",
    fg="white",
    activebackground="#4a4a68",
    activeforeground="white",
    bd=0,
    pady=P(12),
    cursor="hand2"
)

btn_app.pack(
    side=tk.LEFT,
    fill=tk.X,
    expand=True,
    padx=(
        0,
        P(6)
    )
)


btn_calib = tk.Button(
    btn_frame,
    text="Calibration",
    command=ouvrir_calibration,
    font=(
        "Segoe UI",
        F(12),
        "bold"
    ),
    bg="#2196f3",
    fg="white",
    activebackground="#1e88e5",
    activeforeground="white",
    bd=0,
    pady=P(12),
    cursor="hand2"
)

btn_calib.pack(
    side=tk.RIGHT,
    fill=tk.X,
    expand=True,
    padx=(
        P(6),
        0
    )
)


# ==========================================
# CARD 2 - MACHINE POWER
# ==========================================

card_switch = tk.Frame(
    app,
    bg="#2b2b3d",
    bd=0
)

card_switch.pack(
    fill=tk.X,
    padx=P(30),
    pady=P(6),
    ipady=P(8)
)


lbl_switch = tk.Label(
    card_switch,
    text="MACHINE POWER",
    font=(
        "Segoe UI",
        F(12),
        "bold"
    ),
    fg="#8a8a9e",
    bg="#2b2b3d"
)

lbl_switch.pack(
    anchor=tk.W,
    padx=P(24),
    pady=(
        P(10),
        P(6)
    )
)


btn_switch = tk.Button(
    card_switch,
    text="SWITCH ON",
    command=switch_machine,
    font=(
        "Segoe UI",
        F(15),
        "bold"
    ),
    bg="#555555",
    fg="white",
    activebackground="#666666",
    activeforeground="white",
    bd=0,
    pady=P(14),
    cursor="hand2"
)

btn_switch.pack(
    fill=tk.X,
    padx=P(24),
    pady=(
        P(6),
        P(14)
    )
)


# ==========================================
# CARD 3 - NEW ACQUISITION
# ==========================================

card_acq = tk.Frame(
    app,
    bg="#2b2b3d",
    bd=0
)

card_acq.pack(
    fill=tk.X,
    padx=P(30),
    pady=P(6),
    ipady=P(8)
)


lbl_card2 = tk.Label(
    card_acq,
    text="NEW ACQUISITION",
    font=(
        "Segoe UI",
        F(12),
        "bold"
    ),
    fg="#8a8a9e",
    bg="#2b2b3d"
)

lbl_card2.pack(
    anchor=tk.W,
    padx=P(24),
    pady=(
        P(10),
        P(6)
    )
)


lbl_saisie = tk.Label(
    card_acq,
    text="Acquisition Folder Name:",
    font=(
        "Segoe UI",
        F(13)
    ),
    fg="#e0e0e0",
    bg="#2b2b3d"
)

lbl_saisie.pack(
    anchor=tk.W,
    padx=P(24),
    pady=(
        P(2),
        P(2)
    )
)


entree_nom = tk.Entry(
    card_acq,
    font=(
        "Segoe UI",
        F(16)
    ),
    bg="#1e1e2e",
    fg="white",
    insertbackground="white",
    bd=1,
    relief=tk.SOLID
)

entree_nom.pack(
    fill=tk.X,
    padx=P(24),
    pady=P(6),
    ipady=P(6)
)

entree_nom.bind(
    "<Return>",
    lancer_acquisition
)


btn_acq = tk.Button(
    card_acq,
    text="Start Acquisition",
    command=lancer_acquisition,
    font=(
        "Segoe UI",
        F(15),
        "bold"
    ),
    bg="#4caf50",
    fg="white",
    activebackground="#43a047",
    activeforeground="white",
    bd=0,
    pady=P(14),
    cursor="hand2"
)

btn_acq.pack(
    fill=tk.X,
    padx=P(24),
    pady=(
        P(10),
        P(14)
    )
)


# ==========================================
# CARD 4 - CLOUD TRANSFER
# ==========================================

card_cloud = tk.Frame(
    app,
    bg="#2b2b3d",
    bd=0
)

card_cloud.pack(
    fill=tk.X,
    padx=P(30),
    pady=P(6),
    ipady=P(8)
)


lbl_card3 = tk.Label(
    card_cloud,
    text="CLOUD TRANSFER",
    font=(
        "Segoe UI",
        F(12),
        "bold"
    ),
    fg="#8a8a9e",
    bg="#2b2b3d"
)

lbl_card3.pack(
    anchor=tk.W,
    padx=P(24),
    pady=(
        P(10),
        P(6)
    )
)


btn_cloud = tk.Button(
    card_cloud,
    text="Save to Cloud",
    command=toggle_cloud_expansion,
    font=(
        "Segoe UI",
        F(14),
        "bold"
    ),
    bg="#9c27b0",
    fg="white",
    activebackground="#8e24aa",
    activeforeground="white",
    bd=0,
    pady=P(12),
    cursor="hand2"
)

btn_cloud.pack(
    fill=tk.X,
    padx=P(24),
    pady=(
        P(6),
        P(10)
    )
)


# ==========================================
# CLOUD EXPANDED CONTENT
# ==========================================

frame_cloud_content = tk.Frame(
    card_cloud,
    bg="#2b2b3d"
)


# ==========================================
# CHECK ALL / NONE
# ==========================================

frame_select_bar = tk.Frame(
    frame_cloud_content,
    bg="#2b2b3d"
)

frame_select_bar.pack(
    fill=tk.X,
    pady=(
        P(4),
        P(8)
    )
)


btn_all = tk.Button(
    frame_select_bar,
    text="[X] Check All",
    command=select_all_items,
    font=(
        "Segoe UI",
        F(14),
        "bold"
    ),
    bg="#3a3a52",
    fg="#e0e0e0",
    activebackground="#4a4a68",
    activeforeground="white",
    bd=0,
    pady=P(8),
    cursor="hand2"
)

btn_all.pack(
    side=tk.LEFT,
    fill=tk.X,
    expand=True,
    padx=(
        0,
        P(5)
    )
)


btn_none = tk.Button(
    frame_select_bar,
    text="[ ] Check None",
    command=select_none_items,
    font=(
        "Segoe UI",
        F(14),
        "bold"
    ),
    bg="#3a3a52",
    fg="#e0e0e0",
    activebackground="#4a4a68",
    activeforeground="white",
    bd=0,
    pady=P(8),
    cursor="hand2"
)

btn_none.pack(
    side=tk.RIGHT,
    fill=tk.X,
    expand=True,
    padx=(
        P(5),
        0
    )
)


# ==========================================
# SCROLLABLE CLOUD LIST
# ==========================================

frame_scroll_box = tk.Frame(
    frame_cloud_content,
    bg="#1e1e2e",
    height=int(
        220 * SCALE
    )
)

frame_scroll_box.pack(
    fill=tk.X,
    pady=P(6)
)

frame_scroll_box.pack_propagate(
    False
)


canvas_scroll = tk.Canvas(
    frame_scroll_box,
    bg="#1e1e2e",
    highlightthickness=0
)

scrollbar = tk.Scrollbar(
    frame_scroll_box,
    orient="vertical",
    command=canvas_scroll.yview
)

scrollable_frame = tk.Frame(
    canvas_scroll,
    bg="#1e1e2e"
)


scrollable_frame.bind(
    "<Configure>",
    lambda e:
        canvas_scroll.configure(
            scrollregion=canvas_scroll.bbox(
                "all"
            )
        )
)


canvas_scroll.create_window(
    (0, 0),
    window=scrollable_frame,
    anchor="nw"
)

canvas_scroll.configure(
    yscrollcommand=scrollbar.set
)


canvas_scroll.pack(
    side="left",
    fill="both",
    expand=True,
    padx=P(8),
    pady=P(8)
)

scrollbar.pack(
    side="right",
    fill="y",
    pady=P(8)
)


# ==========================================
# CLOUD STATUS
# ==========================================

lbl_transfer_status = tk.Label(
    frame_cloud_content,
    text="",
    font=(
        "Segoe UI",
        F(14),
        "italic"
    ),
    fg="#81c784",
    bg="#2b2b3d"
)

lbl_transfer_status.pack(
    pady=P(4)
)


# ==========================================
# RCLONE UPLOAD BUTTON
# ==========================================

btn_rclone_upload = tk.Button(
    frame_cloud_content,
    text="Upload Selected via Rclone",
    command=envoyer_fichiers_rclone,
    font=(
        "Segoe UI",
        F(13),
        "bold"
    ),
    bg="#4caf50",
    fg="white",
    activebackground="#43a047",
    activeforeground="white",
    bd=0,
    pady=P(12),
    cursor="hand2"
)

btn_rclone_upload.pack(
    fill=tk.X,
    pady=(
        P(4),
        P(10)
    )
)


# ==========================================
# STATUS / CONSOLE
# ==========================================

lbl_status = tk.Label(
    app,
    text="",
    font=(
        "Segoe UI",
        F(12),
        "italic"
    ),
    fg="#e0e0e0",
    bg="#1e1e2e",
    wraplength=P(580),
    justify=tk.CENTER
)

lbl_status.pack(
    fill=tk.X,
    padx=P(30),
    pady=P(10)
)


# ==========================================
# EXIT BUTTON
# ==========================================

btn_quitter = tk.Button(
    app,
    text="EXIT APPLICATION",
    command=app.quit,
    font=(
        "Segoe UI",
        F(15),
        "bold"
    ),
    bg="#d32f2f",
    fg="white",
    activebackground="#b71c1c",
    activeforeground="white",
    bd=0,
    pady=P(16),
    cursor="hand2"
)

btn_quitter.pack(
    side=tk.BOTTOM,
    fill=tk.X,
    padx=P(30),
    pady=(
        P(10),
        P(20)
    )
)


app.after(
    5000,
    actualiser_compteurs_png
)


# ==========================================
# START APPLICATION
# ==========================================

app.mainloop()
