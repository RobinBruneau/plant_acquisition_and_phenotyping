import os
import sys
import json
import subprocess
import tkinter as tk
from tkinter import messagebox
import time
from datetime import datetime, date
from PIL import Image, ImageTk
import pyautogui
import numpy as np
import matplotlib.pyplot as plt

import glob
import re
import shutil
import threading

# ==========================================
# CONFIGURATION
# ==========================================

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

DOSSIER_IMAGES = r"D:\data"

# Local data folder at the repository root (../data),
# where spec.txt and the copied images are stored
DOSSIER_SAUVEGARDE = os.path.join(
    os.path.dirname(BASE_DIR),
    "data"
)

# LemnaControl executable
FICHIER_EXECUTABLE = (
    r"C:\LemnaTec\Software\LemnaControl"
    r"\LemnaControlPhenoAIxpertPro.exe"
)

# Desktop shortcut used to start LemnaControl exactly
# like a double-click (falls back to the exe if missing)
RACCOURCI_EXECUTABLE = os.path.join(
    os.path.expanduser("~"),
    "Desktop",
    "Lemna Control Pheno AIxpertPro.lnk"
)

# Calibration file
FICHIER_CALIBRATION = os.path.join(
    BASE_DIR,
    "calibration_zones.json"
)

# Image monitor
# An acquisition is considered complete when it has
# more than NB_IMAGES_MIN images and no new / modified
# image for DELAI_STABLE_SEC seconds. Its images are
# then copied to DOSSIER_SAUVEGARDE/<acq>/image/.
# Late images are copied the same way.
NB_IMAGES_MIN = 50

DELAI_STABLE_SEC = 30

# Acquisitions followed: local folders touched in
# the last FENETRE_SURVEILLANCE_SEC seconds
FENETRE_SURVEILLANCE_SEC = 24 * 3600

SOUS_DOSSIER_IMAGES = "image"

# Copied images are renamed side_xxx / top_xxx,
# xxx = angle / PAS_ANGLE_DEG (000 = 0 deg, 001 = 10 deg...)
PAS_ANGLE_DEG = 10


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

# True while a switch or an acquisition is running
process_en_cours = False

monitor_expanded = False

# acquisition name -> row Label in the monitor list
lignes_monitor = {}

# acquisition name -> last copy result
# {"en_cours": bool, "copiees": int, "erreur": str}
etat_copies = {}

verrou_copies = threading.Lock()


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

        # Same as a double-click: open the desktop
        # shortcut through the Windows shell (its
        # working directory, arguments and options).
        if os.path.isfile(RACCOURCI_EXECUTABLE):

            os.startfile(
                RACCOURCI_EXECUTABLE
            )

        # Fallback: start the exe from its own folder,
        # like the shortcut does.
        else:

            subprocess.Popen(
                [FICHIER_EXECUTABLE],
                cwd=os.path.dirname(
                    FICHIER_EXECUTABLE
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

    global process_en_cours

    process_en_cours = en_cours

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
# DETECT REAL MACHINE STATE
#
# Clicks System, then reads the buttons:
#   Initialise green + Shutdown not red -> "off"
#   Shutdown red + Initialise not green -> "on"
# Anything else -> None (unknown)
# ==========================================

def detecter_etat_machine(
    timeout_sec=3
):

    succes, _ = cliquer_zone(
        "system"
    )

    if not succes:

        return None

    temps_debut = time.time()

    while True:

        time.sleep(
            0.5
        )

        try:

            app.update()

        except Exception:

            pass

        init_vert = verifier_bouton_vert(
            "initialise"
        )

        shut_rouge = verifier_bouton_rouge(
            "shutdown"
        )

        if shut_rouge and not init_vert:

            return "on"

        if init_vert and not shut_rouge:

            return "off"

        if time.time() - temps_debut > timeout_sec:

            return None


# ==========================================
# SWITCH MACHINE ON / OFF
#
# Returns True if the machine ends in the
# requested state, False otherwise.
# ==========================================

def switch_machine():

    global machine_allumee

    global switch_en_cours

    # --------------------------------------
    # PREVENT DOUBLE CLICK / CONCURRENT RUN
    # --------------------------------------

    if switch_en_cours:

        return False

    if process_en_cours:

        afficher_status(
            "Error: A process is already running.",
            "#e57373"
        )

        return False

    # --------------------------------------
    # CALIBRATION REQUIRED
    # --------------------------------------

    if not charger_zones():

        afficher_status(
            "Error: Please calibrate zones first!",
            "#e57373"
        )

        return False

    switch_en_cours = True

    btn_switch.config(
        state=tk.DISABLED,
        bg="#555555",
        fg="#aaaaaa"
    )

    definir_etat_acquisition(
        True
    )

    # --------------------------------------
    # CHECK REAL STATE BEFORE ACTING
    # --------------------------------------

    afficher_status(
        "Checking machine state...",
        "#e0e0e0"
    )

    etat = detecter_etat_machine()

    if etat is None:

        afficher_status(
            "Error: Could not determine machine state "
            "(is LemnaControl open?).",
            "#e57373"
        )

        terminer_switch()

        return False

    if etat == "on" and not machine_allumee:

        machine_allumee = True

        afficher_status(
            "Machine was already ON. "
            "State updated, nothing done.",
            "#ffb74d"
        )

        terminer_switch()

        return True

    if etat == "off" and machine_allumee:

        machine_allumee = False

        afficher_status(
            "Machine was already OFF. "
            "State updated, nothing done.",
            "#ffb74d"
        )

        terminer_switch()

        return True

    # ======================================
    # SWITCH ON  (machine verified OFF:
    # Initialise green, Shutdown not red)
    # ======================================

    if not machine_allumee:

        afficher_status(
            "Power ON: Machine is OFF. "
            "Clicking Initialise...",
            "#e0e0e0"
        )

        succes, msg = cliquer_zone(
            "initialise"
        )

        if not succes:

            afficher_status(
                f"Error clicking Initialise: {msg}",
                "#e57373"
            )

            terminer_switch()

            return False

        time.sleep(
            0.5
        )

        afficher_status(
            "Power ON: Waiting for Shutdown "
            "to turn red...",
            "#e0e0e0"
        )

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

            return False

        machine_allumee = True

        afficher_status(
            "Machine is ON.",
            "#81c784"
        )

        terminer_switch()

        return True

    # ======================================
    # SWITCH OFF  (machine verified ON:
    # Shutdown red, Initialise not green)
    # ======================================

    afficher_status(
        "Power OFF: Machine is ON. "
        "Clicking Shutdown...",
        "#e0e0e0"
    )

    succes, msg = cliquer_zone(
        "shutdown"
    )

    if not succes:

        afficher_status(
            f"Error clicking Shutdown: {msg}",
            "#e57373"
        )

        terminer_switch()

        return False

    time.sleep(
        0.5
    )

    afficher_status(
        "Power OFF: Waiting for Initialise "
        "to turn green...",
        "#e0e0e0"
    )

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

        return False

    machine_allumee = False

    afficher_status(
        "Machine is OFF.",
        "#81c784"
    )

    terminer_switch()

    return True


# ==========================================
# EXIT APPLICATION
#
# Switches the machine OFF first if it
# is ON (after confirmation).
# ==========================================

def quitter_application():

    global machine_allumee

    if switch_en_cours or process_en_cours:

        afficher_status(
            "Cannot exit: a process is in progress.",
            "#e57373"
        )

        return

    etat = None

    if charger_zones():

        afficher_status(
            "Checking machine state before exit...",
            "#e0e0e0"
        )

        etat = detecter_etat_machine()

    if etat == "on" or (etat is None and machine_allumee):

        # Machine ON: switch it OFF, then exit.
        # If switch OFF fails, stay open.
        machine_allumee = True

        if not switch_machine() or machine_allumee:

            messagebox.showerror(
                "Exit application",
                "Switch OFF failed.\n"
                "The application was not closed.",
                parent=app
            )

            return

    elif etat is None:

        if not messagebox.askyesno(
            "Exit application",
            "Could not determine the machine state.\n\n"
            "Exit anyway?",
            parent=app
        ):

            afficher_status(
                "Exit cancelled.",
                "#e0e0e0"
            )

            return

    app.destroy()


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

    if switch_en_cours or process_en_cours:

        afficher_status(
            "Error: A process is already running.",
            "#e57373"
        )

        return

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

    caracteres_interdits = set('<>:"/\\|?*')

    if (
        any(c in caracteres_interdits for c in nom_acq)
        or nom_acq.endswith(".")
        or nom_acq in (".", "..")
    ):

        afficher_status(
            f"Error: Invalid acquisition name '{nom_acq}'. "
            'Do not use < > : " / \\ | ? * '
            "or a trailing dot.",
            "#e57373"
        )

        entree_nom.focus_set()

        return

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

    # Images of a previous (possibly failed) run
    # with the same name may already be in D:\data
    if os.path.exists(
        os.path.join(
            DOSSIER_IMAGES,
            nom_acq
        )
    ):

        afficher_status(
            f"Error: Folder '{nom_acq}' already exists "
            f"in {DOSSIER_IMAGES} (images from a previous "
            "acquisition). Choose another name.",
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
# IMAGE MONITOR - FOLDERS TO FOLLOW
# ==========================================

def recuperer_acquisitions_recentes():

    if not os.path.exists(
        DOSSIER_SAUVEGARDE
    ):

        return []

    limite = time.time() - FENETRE_SURVEILLANCE_SEC

    resultat = []

    for item in os.listdir(
        DOSSIER_SAUVEGARDE
    ):

        item_path = os.path.join(
            DOSSIER_SAUVEGARDE,
            item
        )

        if not os.path.isdir(
            item_path
        ):

            continue

        mtimes = [
            os.path.getmtime(item_path)
        ]

        dossier_img = os.path.join(
            item_path,
            SOUS_DOSSIER_IMAGES
        )

        if os.path.isdir(dossier_img):

            mtimes.append(
                os.path.getmtime(dossier_img)
            )

        if max(mtimes) >= limite:

            resultat.append(
                (os.path.getctime(item_path), item)
            )

    # Most recent acquisition first. On Windows getctime
    # is the folder creation time, so the order stays
    # stable while images are being copied.
    resultat.sort(reverse=True)

    return [item for _, item in resultat]


# ==========================================
# IMAGE MONITOR - SCAN SOURCE IMAGES
#
# Images are written by LemnaControl to
# DOSSIER_IMAGES/<acq>/<date>/...
# ==========================================

# Full-size image name written by LemnaControl, e.g.
# part-0-180.RGB_cameraSide^center^OP_side_010.2026-10-01_142952.png
# -> camera "side", angle 10, run "2026-10-01_142952"
# Thumbnails (TN/ folder, names ending in _80, _125...)
# do not match and are ignored.
MOTIF_IMAGE = re.compile(
    r"_(side|top)_(\d+)\.(\d{4}-\d{2}-\d{2}_\d{6})"
    r"\.(png|jpe?g)$",
    re.IGNORECASE
)


def nom_image_dest(
    camera,
    angle,
    extension
):

    # side_000 = 0 deg, side_001 = 10 deg, ...
    index = int(angle) // PAS_ANGLE_DEG

    return (
        f"{camera.lower()}_{index:03d}"
        f".{extension.lower()}"
    )


def lister_images_source(
    nom_acq
):

    """Returns (images, last_update).

    images: list of (dest_name, path, size, mtime),
    one per camera/angle; if an angle was recorded
    several times, the most recent run wins.
    last_update: newest mtime of any file in the
    folder (thumbnails included), or None.
    """

    dossier = os.path.join(
        DOSSIER_IMAGES,
        nom_acq
    )

    choisies = {}

    derniere_maj = None

    if not os.path.isdir(
        dossier
    ):

        return [], None

    for racine, sous_dossiers, fichiers in os.walk(
        dossier
    ):

        # Thumbnails folder: never copied
        miniatures = (
            os.path.basename(racine).upper() == "TN"
        )

        for nom in fichiers:

            chemin = os.path.join(
                racine,
                nom
            )

            try:

                st = os.stat(chemin)

            except OSError:

                continue

            if derniere_maj is None or st.st_mtime > derniere_maj:

                derniere_maj = st.st_mtime

            if miniatures:

                continue

            m = MOTIF_IMAGE.search(
                nom
            )

            if not m:

                continue

            camera, angle, run, ext = m.groups()

            dest_name = nom_image_dest(
                camera,
                angle,
                ext
            )

            precedent = choisies.get(
                dest_name
            )

            if precedent is None or run > precedent[0]:

                choisies[dest_name] = (
                    run,
                    chemin,
                    st.st_size,
                    st.st_mtime
                )

    images = [
        (dest_name, chemin, taille, mtime)
        for dest_name, (_, chemin, taille, mtime)
        in sorted(choisies.items())
    ]

    return images, derniere_maj


def images_a_copier(
    nom_acq,
    images
):

    dossier_dest = os.path.join(
        DOSSIER_SAUVEGARDE,
        nom_acq,
        SOUS_DOSSIER_IMAGES
    )

    a_copier = []

    for nom, chemin, taille, mtime in images:

        dest = os.path.join(
            dossier_dest,
            nom
        )

        # Already copied from this exact source file
        # (copy2 keeps the modification time)
        try:

            st = os.stat(dest)

            if (
                st.st_size == taille
                and abs(st.st_mtime - mtime) < 2
            ):

                continue

        except OSError:

            pass

        a_copier.append(
            (chemin, dest)
        )

    return a_copier


# ==========================================
# IMAGE MONITOR - COPY (background thread)
# ==========================================

def _copier_images_thread(
    nom_acq,
    a_copier
):

    copiees = 0

    erreur = ""

    try:

        os.makedirs(
            os.path.join(
                DOSSIER_SAUVEGARDE,
                nom_acq,
                SOUS_DOSSIER_IMAGES
            ),
            exist_ok=True
        )

        for chemin, dest in a_copier:

            tmp = dest + ".part"

            shutil.copy2(
                chemin,
                tmp
            )

            os.replace(
                tmp,
                dest
            )

            copiees += 1

    except Exception as e:

        erreur = str(e)

    with verrou_copies:

        precedent = etat_copies.get(
            nom_acq,
            {}
        )

        etat_copies[nom_acq] = {
            "en_cours": False,
            "copiees": copiees,
            "deja_copie": precedent.get("deja_copie", False),
            "erreur": erreur,
            "nouveau": True
        }


def lancer_copie(
    nom_acq,
    a_copier
):

    with verrou_copies:

        precedent = etat_copies.get(
            nom_acq,
            {}
        )

        if precedent.get("en_cours"):

            return

        etat_copies[nom_acq] = {
            "en_cours": True,
            "copiees": 0,
            "deja_copie": precedent.get("deja_copie", False)
            or precedent.get("copiees", 0) > 0,
            "erreur": "",
            "nouveau": False
        }

    threading.Thread(
        target=_copier_images_thread,
        args=(nom_acq, a_copier),
        daemon=True
    ).start()


# ==========================================
# IMAGE MONITOR - ONE ACQUISITION
#
# Returns (text, color) for its row.
# ==========================================

def traiter_acquisition(
    nom_acq
):

    images, derniere_maj = lister_images_source(
        nom_acq
    )

    nb = len(images)

    with verrou_copies:

        copie = dict(
            etat_copies.get(
                nom_acq,
                {}
            )
        )

        if copie.get("nouveau"):

            etat_copies[nom_acq]["nouveau"] = False

    # Report a finished copy in the status bar
    if copie.get("nouveau"):

        if copie.get("erreur"):

            afficher_status(
                f"Copy error for '{nom_acq}': "
                f"{copie['erreur']}",
                "#e57373"
            )

        elif copie.get("copiees"):

            if copie.get("deja_copie"):

                afficher_status(
                    f"'{nom_acq}': {copie['copiees']} late "
                    "image(s) copied to ./data/.",
                    "#81c784"
                )

            else:

                afficher_status(
                    f"'{nom_acq}': {copie['copiees']} "
                    "image(s) copied to ./data/.",
                    "#81c784"
                )

    if copie.get("en_cours"):

        return (
            f"{nom_acq}    {nb} img    COPYING...",
            "#64b5f6"
        )

    if nb == 0:

        return (
            f"{nom_acq}    0 img    waiting for images",
            "#78909c"
        )

    age = time.time() - derniere_maj

    if nb <= NB_IMAGES_MIN or age < DELAI_STABLE_SEC:

        if nb <= NB_IMAGES_MIN:

            detail = f"need > {NB_IMAGES_MIN}"

        else:

            reste = int(DELAI_STABLE_SEC - age)

            detail = f"stable in {reste // 60}:{reste % 60:02d}"

        return (
            f"{nom_acq}    {nb} img    UPLOADING "
            f"(last image {int(age)} s ago, {detail})",
            "#ffb74d"
        )

    # Complete: copy missing / late images
    a_copier = images_a_copier(
        nom_acq,
        images
    )

    if a_copier:

        lancer_copie(
            nom_acq,
            a_copier
        )

        return (
            f"{nom_acq}    {nb} img    COPYING "
            f"{len(a_copier)} image(s)...",
            "#64b5f6"
        )

    if copie.get("erreur"):

        return (
            f"{nom_acq}    {nb} img    COPY ERROR",
            "#e57373"
        )

    return (
        f"{nom_acq}    {nb} img    COMPLETE - copied",
        "#81c784"
    )


# ==========================================
# IMAGE MONITOR - PERIODIC REFRESH
#
# Runs every 5 s, even when the list is
# closed, so copies always happen.
# ==========================================

def actualiser_monitor():

    try:

        acquisitions = recuperer_acquisitions_recentes()

        if monitor_expanded and (
            list(lignes_monitor.keys()) != acquisitions
        ):

            construire_liste_monitor(
                acquisitions
            )

        for nom_acq in acquisitions:

            texte, couleur = traiter_acquisition(
                nom_acq
            )

            lbl = lignes_monitor.get(
                nom_acq
            )

            if lbl is not None:

                lbl.config(
                    text=texte,
                    fg=couleur
                )

    except Exception as e:

        afficher_status(
            f"Image monitor error: {e}",
            "#e57373"
        )

    app.after(
        5000,
        actualiser_monitor
    )


def construire_liste_monitor(
    acquisitions
):

    lignes_monitor.clear()

    for widget in (
        scrollable_frame.winfo_children()
    ):

        widget.destroy()

    if not acquisitions:

        tk.Label(
            scrollable_frame,
            text=(
                "No acquisition in the last 24 h."
            ),
            font=(
                "Segoe UI",
                F(12),
                "italic"
            ),
            fg="#8a8a9e",
            bg="#1e1e2e"
        ).pack(
            padx=P(20),
            pady=P(20)
        )

        return

    for nom_acq in acquisitions:

        lbl = tk.Label(
            scrollable_frame,
            text=nom_acq,
            font=(
                "Segoe UI",
                F(12),
                "bold"
            ),
            anchor="w",
            justify=tk.LEFT,
            fg="#e0e0e0",
            bg="#252538",
            padx=P(10),
            pady=P(8)
        )

        lbl.pack(
            fill=tk.X,
            padx=P(8),
            pady=P(4)
        )

        lignes_monitor[nom_acq] = lbl


# ==========================================
# IMAGE MONITOR - SHOW / HIDE LIST
# ==========================================

def toggle_monitor_expansion():

    global monitor_expanded

    if not monitor_expanded:

        app.geometry(
            f"{BASE_WIDTH}x"
            f"{EXPANDED_HEIGHT}+"
            f"{POS_X}+{POS_Y}"
        )

        monitor_expanded = True

        acquisitions = recuperer_acquisitions_recentes()

        construire_liste_monitor(
            acquisitions
        )

        for nom_acq in acquisitions:

            texte, couleur = traiter_acquisition(
                nom_acq
            )

            lignes_monitor[nom_acq].config(
                text=texte,
                fg=couleur
            )

        frame_monitor_content.pack(
            fill=tk.BOTH,
            expand=True,
            padx=P(24),
            pady=(
                0,
                P(12)
            )
        )

        btn_monitor.config(
            text="Hide Image Monitor"
        )

    else:

        frame_monitor_content.pack_forget()

        app.geometry(
            f"{BASE_WIDTH}x"
            f"{BASE_HEIGHT}+"
            f"{POS_X}+{POS_Y}"
        )

        btn_monitor.config(
            text="Show Image Monitor"
        )

        monitor_expanded = False


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


var_nom = tk.StringVar()

entree_nom = tk.Entry(
    card_acq,
    textvariable=var_nom,
    font=(
        "Segoe UI",
        F(16)
    ),
    bg="#1e1e2e",
    fg="white",
    insertbackground="white",
    bd=1,
    relief=tk.SOLID,
    highlightthickness=2,
    highlightbackground="#1e1e2e",
    highlightcolor="#1e1e2e"
)


def verifier_nom(*_):
    """Color the name field: green if usable, red if it
    already exists (or contains forbidden characters)."""

    nom = var_nom.get().strip()

    if not nom:
        couleur_texte = "white"
        couleur_bord = "#1e1e2e"

    elif (
        any(c in '<>:"/\\|?*' for c in nom)
        or nom.endswith(".")
        or os.path.exists(os.path.join(DOSSIER_SAUVEGARDE, nom))
        or os.path.exists(os.path.join(DOSSIER_IMAGES, nom))
    ):
        couleur_texte = "#e57373"
        couleur_bord = "#e57373"

    else:
        couleur_texte = "#81c784"
        couleur_bord = "#81c784"

    entree_nom.config(
        fg=couleur_texte,
        highlightbackground=couleur_bord,
        highlightcolor=couleur_bord
    )


var_nom.trace_add("write", verifier_nom)

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
# CARD 4 - IMAGE MONITOR
# ==========================================

card_monitor = tk.Frame(
    app,
    bg="#2b2b3d",
    bd=0
)

card_monitor.pack(
    fill=tk.X,
    padx=P(30),
    pady=P(6),
    ipady=P(8)
)


lbl_card_monitor = tk.Label(
    card_monitor,
    text="IMAGE MONITOR",
    font=(
        "Segoe UI",
        F(12),
        "bold"
    ),
    fg="#8a8a9e",
    bg="#2b2b3d"
)

lbl_card_monitor.pack(
    anchor=tk.W,
    padx=P(24),
    pady=(
        P(10),
        P(6)
    )
)


btn_monitor = tk.Button(
    card_monitor,
    text="Show Image Monitor",
    command=toggle_monitor_expansion,
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

btn_monitor.pack(
    fill=tk.X,
    padx=P(24),
    pady=(
        P(6),
        P(10)
    )
)


# ==========================================
# MONITOR EXPANDED CONTENT
# ==========================================

frame_monitor_content = tk.Frame(
    card_monitor,
    bg="#2b2b3d"
)


lbl_monitor_info = tk.Label(
    frame_monitor_content,
    text=(
        f"Complete = more than {NB_IMAGES_MIN} images and "
        f"no new image for {DELAI_STABLE_SEC} s. "
        "Complete acquisitions (and late images) are "
        "copied automatically to ./data/<acq>/image/."
    ),
    font=(
        "Segoe UI",
        F(11),
        "italic"
    ),
    fg="#8a8a9e",
    bg="#2b2b3d",
    wraplength=P(540),
    justify=tk.LEFT
)

lbl_monitor_info.pack(
    fill=tk.X,
    pady=(
        P(4),
        P(4)
    )
)


# ==========================================
# SCROLLABLE MONITOR LIST
# ==========================================

frame_scroll_box = tk.Frame(
    frame_monitor_content,
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
    command=quitter_application,
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
    2000,
    actualiser_monitor
)


# ==========================================
# START APPLICATION
# ==========================================

app.protocol(
    "WM_DELETE_WINDOW",
    quitter_application
)

app.mainloop()
