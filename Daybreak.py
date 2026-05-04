# Imports – Bring in cryptographic libraries (AES‑256, scrypt) and PyQt6 for the graphical interface.
import sys
import os
import json
import time
import math
import string
import base64
import hashlib
import gc
from pathlib import Path

# --- EXPERT SECURITY IMPORTS ---
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

# --- UI IMPORTS ---
from PyQt6.QtWidgets import (QApplication, QMainWindow, QStackedWidget, QWidget, 
                             QVBoxLayout, QPushButton, QLabel, QLineEdit, 
                             QHBoxLayout, QFrame, QSlider, QListWidget, 
                             QMessageBox, QComboBox, QInputDialog, 
                             QGraphicsOpacityEffect)
from PyQt6.QtCore import Qt, QTimer, QRectF, QPropertyAnimation, QEasingCurve
from PyQt6.QtGui import QPixmap, QColor, QPainter, QPen, QFont

# =============================================================================
# 0. RESOURCE RESOLVER
# Resource resolver – Helper function resource_path() that finds images and files correctly whether the app runs as a script or as a compiled .exe.
# Why it matters – Ensures the logo and background image load reliably on any computer.
# =============================================================================
def resource_path(relative_path):
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base_path, relative_path)

# =============================================================================
# 1. UI: REAL-TIME ENTROPY GAUGE
# Circular gauge – Draws a ring that fills from 0% to 100% as you type a password.
# Entropy calculation – Counts character types (lowercase, uppercase, digits, symbols) to estimate password strength.
# Colour feedback – Red (weak), yellow (moderate), cyan (strong) – gives instant visual feedback.
# =============================================================================
class StrengthGauge(QWidget):
    def __init__(self):
        super().__init__()
        self.setFixedSize(160, 160)
        self.percent = 0
        self.color = QColor("#2A2F35")

    def update_strength(self, password):
        if not password:
            self.percent = 0; self.update(); return
        
        pool = 0
        if any(c.islower() for c in password): pool += 26
        if any(c.isupper() for c in password): pool += 26
        if any(c.isdigit() for c in password): pool += 10
        if any(c in string.punctuation for c in password): pool += 32
        
        entropy = len(password) * math.log2(pool) if pool > 0 else 0
        self.percent = min(100, int((entropy / 128.0) * 100))
        
        if entropy < 50: self.color = QColor("#FF5F5F")
        elif entropy < 80: self.color = QColor("#FFBD2E")
        else: self.color = QColor("#00D4FF")
        self.update()

    def paintEvent(self, event):
        p = QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(15, 15, 130, 130)
        p.setPen(QPen(QColor("#2A2F35"), 12, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawArc(rect, 0, 360 * 16)
        p.setPen(QPen(self.color, 12, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawArc(rect, 90 * 16, -int((self.percent / 100) * 360 * 16))
        p.setPen(self.color); p.setFont(QFont("Segoe UI", 22, QFont.Weight.Bold))
        p.drawText(rect, Qt.AlignmentFlag.AlignCenter, f"{self.percent}%")

# =============================================================================
# 2. SECURITY ENGINE (Zero-Knowledge AES-256)
# Key derivation – Uses scrypt to turn your master password into a secure 32‑byte key (memory‑hard, resistant to brute force).
# Encryption – Saves the vault to vault.db using AES‑256‑GCM (authenticated encryption – protects both confidentiality and integrity).
# Emergency backdoors (demo only) – Hardcoded root hash and recovery key allow bypass; clearly labelled as insecure for production.
# Deterministic generator – Produces the same password from the same seed + master key – useful if you lose the vault but remember the seed.
# =============================================================================
class SecurityEngine:
    def __init__(self):
        self.key = None 
        self.vault = {}
        self.is_online = True 
        self.db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "vault.db")
        self._ROOT_HASH = hashlib.sha256(b"ROOT-ADMIN-2026").hexdigest()
        self._RECOVERY_KEY = "DAYBREAK-X9-RECOVERY-AUTH"

    def _derive(self, pwd):
        salt = b'daybreak_expert_salt_v8'
        kdf = Scrypt(salt=salt, length=32, n=2**14, r=8, p=1)
        self.key = kdf.derive(pwd.encode())

    def authenticate(self, user, pwd):
        if user == "Jheirom" and pwd == "1234":
            self._derive(pwd); self._load(); return True
        return False

    def auth_root(self, pwd):
        if hashlib.sha256(pwd.encode()).hexdigest() == self._ROOT_HASH:
            self._derive("1234"); self._load(); return True
        return False

    def auth_recovery(self, key):
        if key == self._RECOVERY_KEY:
            self._derive("1234"); self._load(); return True
        return False

    def _save(self):
        if not self.key: return
        aesgcm = AESGCM(self.key)
        nonce = os.urandom(12)
        ciphertext = aesgcm.encrypt(nonce, json.dumps(self.vault).encode(), None)
        with open(self.db_path, "wb") as f: f.write(nonce + ciphertext)

    def _load(self):
        if os.path.exists(self.db_path):
            try:
                with open(self.db_path, "rb") as f:
                    d = f.read(); n, ct = d[:12], d[12:]
                    self.vault = json.loads(AESGCM(self.key).decrypt(n, ct, None).decode())
            except: self.vault = {}

    def modify(self, name, data, delete=False):
        if delete:
            if name in self.vault: del self.vault[name]
        else:
            self.vault[name] = data
        self._save()

    def generate(self, seed, length):
        if not self.key or not seed: return ""
        raw = self.key + seed.lower().strip().encode()
        h = hashlib.sha512(raw).digest()
        chars = string.ascii_letters + string.digits + "!@#$%^&*()"
        return "".join([chars[b % len(chars)] for b in h])[:length]

# =============================================================================
# 3. MAIN UI HUB
# Login window – Username + master password; also offers “ROOT BYPASS” and “Emergency Recovery Key” for demo purposes.
# Vault tab – Stores two types of entries: Login credentials (app, username, password) and Payment cards (card number, expiry, CVV). All saved entries appear in a list.
# Generator tab – Allows you to enter a seed (e.g., “Netflix”), choose a length (8–64), and generate a deterministic, strong password. Includes the StrengthGauge for real‑time feedback.
# Offline mode toggle – Simulates a “read‑only” mode; when offline, you cannot add, modify, or delete entries.
# Persistent storage – The vault is automatically saved (encrypted) after every change and reloaded when you log in.
# =============================================================================
class DaybreakApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.db = SecurityEngine()
        self.setWindowTitle("Daybreak Octave 8")
        self.setFixedSize(850, 750) # Slightly increased height for card fields
        
        self.setStyleSheet("""
            QMainWindow, QWidget { background-color: #0A0D10; color: #E1E1E1; font-family: 'Segoe UI'; }
            QLineEdit, QComboBox { background-color: #12161B; border: 1px solid #2A2F35; border-radius: 4px; padding: 10px; color: white; }
            QPushButton { background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #00D4FF, stop:1 #090979); color: white; border-radius: 4px; padding: 12px; font-weight: bold; border: none; }
            QPushButton#NavBtnActive { background: #1F6FEB; color: white; text-align: left; padding: 15px; }
            QPushButton#NavBtn { background: transparent; text-align: left; padding: 15px; color: #8B949E; }
            QFrame#Sidebar { background-color: #0D1117; border-right: 1px solid #30363D; }
            QFrame#Card { background-color: #161B22; border-radius: 8px; border: 1px solid #30363D; padding: 10px; }
            QListWidget { background: #0D1117; border: 1px solid #2A2F35; border-radius: 4px; }
        """)

        self.stack = QStackedWidget()
        self.setCentralWidget(self.stack)
        self.init_signin()

    def init_signin(self):
        page = QWidget(); layout = QVBoxLayout(page); layout.setContentsMargins(50, 20, 50, 50)
        
        l_path = resource_path("Desktop Password Manager App Logo.png")
        if os.path.exists(l_path):
            l = QLabel(); l.setPixmap(QPixmap(l_path).scaledToWidth(140, Qt.TransformationMode.SmoothTransformation))
            layout.addWidget(l, alignment=Qt.AlignmentFlag.AlignCenter)
            
        h_path = resource_path("image_7d8397.png")
        if os.path.exists(h_path):
            h = QLabel(); h.setPixmap(QPixmap(h_path).scaled(450, 320, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
            layout.addWidget(h, alignment=Qt.AlignmentFlag.AlignCenter)

        self.u_in = QLineEdit(placeholderText="Username (Jheirom)"); self.u_in.setFixedWidth(320)
        self.p_in = QLineEdit(placeholderText="Master Key", echoMode=QLineEdit.EchoMode.Password); self.p_in.setFixedWidth(320)
        
        btn_box = QHBoxLayout()
        root_btn = QPushButton("ROOT BYPASS"); root_btn.setStyleSheet("background: #30363D; color: #FF5F5F;"); root_btn.clicked.connect(self.root_login)
        login_btn = QPushButton("AUTHENTICATE"); login_btn.clicked.connect(self.login)
        btn_box.addWidget(root_btn); btn_box.addWidget(login_btn)
        
        layout.addWidget(self.u_in, alignment=Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.p_in, alignment=Qt.AlignmentFlag.AlignCenter)
        layout.addLayout(btn_box)

        recovery_btn = QPushButton("Emergency Recovery Key Access"); recovery_btn.setStyleSheet("background:transparent; color:#8B949E; text-decoration:underline; font-size:11px;")
        recovery_btn.clicked.connect(self.recovery_login)
        layout.addWidget(recovery_btn, alignment=Qt.AlignmentFlag.AlignCenter)
        
        self.stack.addWidget(page)

    def login(self):
        if self.db.authenticate(self.u_in.text(), self.p_in.text()): self.show_hub()
        else: QMessageBox.warning(self, "Denied", "Authentication Failed.")

    def root_login(self):
        pwd, ok = QInputDialog.getText(self, "Emergency", "Root Password:", QLineEdit.EchoMode.Password)
        if ok and self.db.auth_root(pwd): self.show_hub()

    def recovery_login(self):
        key, ok = QInputDialog.getText(self, "Recovery", "Physical Recovery Key:", QLineEdit.EchoMode.Normal)
        if ok and self.db.auth_recovery(key): self.show_hub()

    def show_hub(self):
        hub = QWidget(); layout = QHBoxLayout(hub); layout.setContentsMargins(0,0,0,0)
        sidebar = QFrame(); sidebar.setObjectName("Sidebar"); sidebar.setFixedWidth(220)
        s_layout = QVBoxLayout(sidebar)
        
        self.nav_btns = []
        for i, name in enumerate(["VAULT", "GENERATOR"]):
            b = QPushButton(name); b.setObjectName("NavBtn" if i > 0 else "NavBtnActive")
            b.clicked.connect(lambda _, x=i: self.switch_tab(x))
            s_layout.addWidget(b); self.nav_btns.append(b)
        
        s_layout.addStretch()
        self.net_btn = QPushButton("STATUS: ONLINE"); self.net_btn.setStyleSheet("color: #00D4FF; background: #161B22;")
        self.net_btn.clicked.connect(self.toggle_net)
        s_layout.addWidget(self.net_btn)
        
        logout = QPushButton("LOGOUT"); logout.setObjectName("NavBtn"); logout.clicked.connect(lambda: self.stack.setCurrentIndex(0))
        s_layout.addWidget(logout)

        self.content = QStackedWidget()
        self.content.addWidget(self.create_vault_tab())
        self.content.addWidget(self.create_gen_tab())
        
        layout.addWidget(sidebar); layout.addWidget(self.content)
        self.stack.addWidget(hub); self.stack.setCurrentIndex(1)

    def toggle_net(self):
        self.db.is_online = not self.db.is_online
        self.net_btn.setText("STATUS: ONLINE" if self.db.is_online else "STATUS: OFFLINE (Read-Only)")
        self.net_btn.setStyleSheet(f"color: {'#00D4FF' if self.db.is_online else '#FF5F5F'}; background: #161B22;")

    def switch_tab(self, i):
        self.content.setCurrentIndex(i)
        for idx, b in enumerate(self.nav_btns): b.setObjectName("NavBtnActive" if idx == i else "NavBtn")
        self.setStyleSheet(self.styleSheet())

    def create_vault_tab(self):
        p = QWidget(); l = QVBoxLayout(p); l.setContentsMargins(40,20,40,20)
        l.addWidget(QLabel("AES-256 MASTER VAULT"))
        
        self.list_w = QListWidget(); self.list_w.addItems(self.db.vault.keys())
        self.list_w.itemClicked.connect(self.fill_fields)
        
        card = QFrame(); card.setObjectName("Card"); c_layout = QVBoxLayout(card)
        
        # New: Type Selector
        self.type_select = QComboBox()
        self.type_select.addItems(["Login Credential", "Payment Card"])
        self.type_select.currentIndexChanged.connect(self.toggle_entry_ui)
        
        self.input_stack = QStackedWidget()
        
        # Login Inputs
        login_w = QWidget(); ll = QVBoxLayout(login_w); ll.setContentsMargins(0,0,0,0)
        self.app_i = QLineEdit(placeholderText="App/Site")
        self.user_i = QLineEdit(placeholderText="Username")
        self.pass_i = QLineEdit(placeholderText="Password")
        ll.addWidget(self.app_i); ll.addWidget(self.user_i); ll.addWidget(self.pass_i)
        
        # Payment Inputs
        pay_w = QWidget(); pl = QVBoxLayout(pay_w); pl.setContentsMargins(0,0,0,0)
        self.c_label_i = QLineEdit(placeholderText="Card Label (e.g. Bank Visa)")
        self.c_holder_i = QLineEdit(placeholderText="Cardholder Name")
        self.c_num_i = QLineEdit(placeholderText="Card Number")
        self.c_exp_i = QLineEdit(placeholderText="Expiry (MM/YY)"); self.c_cvv_i = QLineEdit(placeholderText="CVV")
        pl.addWidget(self.c_label_i); pl.addWidget(self.c_holder_i); pl.addWidget(self.c_num_i); pl.addWidget(self.c_exp_i); pl.addWidget(self.c_cvv_i)
        
        self.input_stack.addWidget(login_w); self.input_stack.addWidget(pay_w)
        
        btns = QHBoxLayout()
        add_b = QPushButton("SECURE"); add_b.clicked.connect(self.save_entry)
        del_b = QPushButton("PURGE"); del_b.setStyleSheet("background: #30363D; color: #FF5F5F;"); del_b.clicked.connect(self.delete_entry)
        btns.addWidget(add_b); btns.addWidget(del_b)
        
        c_layout.addWidget(QLabel("ENTRY TYPE"))
        c_layout.addWidget(self.type_select)
        c_layout.addWidget(self.input_stack)
        c_layout.addLayout(btns)
        
        l.addWidget(self.list_w); l.addWidget(card); return p

    def toggle_entry_ui(self, index):
        self.input_stack.setCurrentIndex(index)

    def fill_fields(self, item):
        e = self.db.vault[item.text()]
        if e.get('type') == 'payment':
            self.type_select.setCurrentIndex(1)
            self.c_label_i.setText(item.text())
            self.c_holder_i.setText(e['holder']); self.c_num_i.setText(e['num'])
            self.c_exp_i.setText(e['exp']); self.c_cvv_i.setText(e['cvv'])
        else:
            self.type_select.setCurrentIndex(0)
            self.app_i.setText(item.text())
            self.user_i.setText(e['user']); self.pass_i.setText(e['pass'])

    def save_entry(self):
        if not self.db.is_online: 
            QMessageBox.warning(self, "Blocked", "Modifications require authenticated online connection."); return
        
        if self.type_select.currentIndex() == 0: # Login
            name = self.app_i.text()
            if not name: return
            data = {"type": "login", "user": self.user_i.text(), "pass": self.pass_i.text(), "ts": time.time()}
        else: # Payment
            name = self.c_label_i.text()
            if not name: return
            data = {"type": "payment", "holder": self.c_holder_i.text(), "num": self.c_num_i.text(), 
                    "exp": self.c_exp_i.text(), "cvv": self.c_cvv_i.text(), "ts": time.time()}
        
        self.db.modify(name, data)
        self.list_w.clear(); self.list_w.addItems(self.db.vault.keys())

    def delete_entry(self):
        if not self.db.is_online: return
        name = self.app_i.text() if self.type_select.currentIndex() == 0 else self.c_label_i.text()
        self.db.modify(name, {}, delete=True)
        self.list_w.clear(); self.list_w.addItems(self.db.vault.keys())

    def create_gen_tab(self):
        p = QWidget(); l = QVBoxLayout(p); l.setContentsMargins(40,40,40,40)
        l.addWidget(QLabel("DETERMINISTIC ENTROPY GENERATOR"))
        self.gauge = StrengthGauge()
        l.addWidget(self.gauge, alignment=Qt.AlignmentFlag.AlignCenter)
        
        card = QFrame(); card.setObjectName("Card"); cl = QVBoxLayout(card)
        self.seed_in = QLineEdit(placeholderText="Enter Seed (e.g., Netflix, Bank)"); self.seed_in.textChanged.connect(self.update_gen)
        self.len_sld = QSlider(Qt.Orientation.Horizontal); self.len_sld.setRange(8, 64); self.len_sld.setValue(16); self.len_sld.valueChanged.connect(self.update_gen)
        self.len_lbl = QLabel("Length: 16")
        self.gen_out = QLineEdit(); self.gen_out.setReadOnly(True); self.gen_out.setStyleSheet("color: #00D4FF; font-size: 18px; text-align: center; border:none;")
        copy_b = QPushButton("COPY PASSWORD"); copy_b.clicked.connect(lambda: QApplication.clipboard().setText(self.gen_out.text()))
        
        cl.addWidget(self.seed_in); cl.addWidget(self.len_lbl); cl.addWidget(self.len_sld); cl.addWidget(self.gen_out); cl.addWidget(copy_b)
        l.addWidget(card); l.addStretch(); return p

    def update_gen(self):
        val = self.len_sld.value(); self.len_lbl.setText(f"Length: {val}")
        pwd = self.db.generate(self.seed_in.text(), val)
        self.gen_out.setText(pwd); self.gauge.update_strength(pwd)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    ex = DaybreakApp(); ex.show()
    sys.exit(app.exec())
