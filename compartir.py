import http.server
import socketserver
import socket
import qrcode
import os
import cgi
import io
import urllib.parse
import string
import platform
import sys
import http.cookies
import logging
from datetime import datetime
import urllib.request
import webbrowser
import threading
import time
import mimetypes
import hashlib
import json
import zipfile
import tempfile
import tkinter as tk
from tkinter import simpledialog, messagebox
from PIL import Image, ImageTk
import uuid
import ssl
import secrets

# --- SEGURIDAD AVANZADA ---
def hash_password(password):
    salt = secrets.token_hex(16)
    hash_hex = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt.encode('utf-8'), 100000).hex()
    return f"pbkdf2:sha256:100000${salt}${hash_hex}"

def verify_password(password, stored_hash):
    if stored_hash.startswith("pbkdf2:"):
        parts = stored_hash.split("$")
        if len(parts) == 3:
            header, salt, hash_hex = parts
            algo = header.split(":")[1]
            iterations = int(header.split(":")[2])
            computed_hash = hashlib.pbkdf2_hmac(algo, password.encode('utf-8'), salt.encode('utf-8'), iterations).hex()
            return secrets.compare_digest(computed_hash, hash_hex)
    else:
        computed_hash = hashlib.sha256(password.encode('utf-8')).hexdigest()
        return secrets.compare_digest(computed_hash, stored_hash)
    return False

# --- ARCHIVO DE CONFIGURACIÓN ---
def get_config_path():
    app_data = os.environ.get('APPDATA') or os.path.expanduser('~')
    app_folder = os.path.join(app_data, "PortalArchivosPremium")
    if not os.path.exists(app_folder):
        os.makedirs(app_folder)
    return os.path.join(app_folder, "config.json")

CONFIG_FILE = get_config_path()

# --- CARGAR CONFIGURACIÓN O CONFIGURAR ---
def load_or_create_config():
    default_config = {
        "PASSWORD_HASH": "", 
        "AUTO_OPEN_BROWSER": False,
        "NGROK_TOKEN": "",
        "NGROK_DOMAIN": "",
        "NGROK_REGION": "sa"
    }
    
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r') as f:
                return json.load(f)
        except:
            return default_config
            
    # Primera vez: Configuración con Ventanas (GUI)
    root = tk.Tk()
    root.withdraw() # Esconder ventana principal
    
    messagebox.showinfo("Configuración", "Bienvenido al Portal de Archivos.\nVamos a configurar tu app por primera vez.")
    
    pw = simpledialog.askstring("Paso 1/2", "Elige una contraseña para tu portal:", show='*')
    while not pw:
        pw = simpledialog.askstring("Error", "La contraseña es obligatoria para tu seguridad.\nElige una contraseña:", show='*')
        if pw is None: sys.exit(0) # Si cancela, cerramos
    
    default_config["PASSWORD_HASH"] = hash_password(pw)
    
    use_ngrok = messagebox.askyesno("Paso 2/2", "¿Quieres usar Ngrok para acceso por Internet/Datos?\n(Necesitarás tu token de la web de Ngrok)")
    
    if use_ngrok:
        token = simpledialog.askstring("Ngrok", "Pega tu NGROK_TOKEN aquí:\n(Consíguelo en dashboard.ngrok.com)")
        if token:
            default_config["NGROK_TOKEN"] = token
            dom = simpledialog.askstring("Ngrok", "Si tienes un dominio gratuito, pégalo aquí (opcional):")
            if dom:
                default_config["NGROK_DOMAIN"] = dom
    
    try:
        with open(CONFIG_FILE, 'w') as f:
            json.dump(default_config, f, indent=4)
        messagebox.showinfo("Éxito", "¡Configuración guardada!\nLa app se iniciará ahora.")
    except Exception as e:
        messagebox.showerror("Error", f"No se pudo guardar la configuración: {e}")
        
    root.destroy()
    return default_config

# Inicializar configuración
CONF = load_or_create_config()

BASE_PORT = 8000
MAX_PORT_ATTEMPTS = 10
PASSWORD_HASH = CONF["PASSWORD_HASH"]
AUTO_OPEN_BROWSER = CONF["AUTO_OPEN_BROWSER"]
NGROK_TOKEN = CONF["NGROK_TOKEN"]
NGROK_DOMAIN = CONF["NGROK_DOMAIN"]
NGROK_REGION = CONF["NGROK_REGION"]

# --- SEGURIDAD Y SESIONES ---
ACTIVE_SESSIONS = {} # {session_id: expiry_timestamp}
LOGIN_ATTEMPTS = {}  # {ip: {'count': N, 'block_until': timestamp}}
MAX_UPLOAD_SIZE = 2 * 1024 * 1024 * 1024 # 2GB por defecto
# Token de solo lectura para visores externos (no expone el hash de la contraseña)
VIEWER_TOKEN = secrets.token_urlsafe(32)

# --- HELPERS ---

logging.basicConfig(
    level=logging.INFO,
    format='[%(levelname)s] %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

def safe_print(msg):
    logger.info(msg)

def get_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(('8.8.8.8', 1))
        IP = s.getsockname()[0]
    except Exception:
        IP = '127.0.0.1'
    finally:
        s.close()
    return IP

def ensure_certificates():
    app_folder = os.path.dirname(CONFIG_FILE)
    cert_path = os.path.join(app_folder, "cert.pem")
    key_path = os.path.join(app_folder, "key.pem")
    
    if os.path.exists(cert_path) and os.path.exists(key_path):
        return cert_path, key_path
        
    safe_print("[i] Generando certificado HTTPS local por primera vez...")
    try:
        from cryptography import x509
        from cryptography.x509.oid import NameOID
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.hazmat.primitives import serialization
        import datetime
        
        private_key = rsa.generate_private_key(
            public_exponent=65537,
            key_size=2048,
        )
        
        subject = issuer = x509.Name([
            x509.NameAttribute(NameOID.COMMON_NAME, u"localhost"),
        ])
        
        cert = x509.CertificateBuilder().subject_name(
            subject
        ).issuer_name(
            issuer
        ).public_key(
            private_key.public_key()
        ).serial_number(
            x509.random_serial_number()
        ).not_valid_before(
            datetime.datetime.utcnow()
        ).not_valid_after(
            datetime.datetime.utcnow() + datetime.timedelta(days=3650)
        ).add_extension(
            x509.SubjectAlternativeName([x509.DNSName(u"localhost"), x509.DNSName(u"127.0.0.1"), x509.DNSName(get_ip())]),
            critical=False,
        ).sign(private_key, hashes.SHA256())
        
        with open(key_path, "wb") as f:
            f.write(private_key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.TraditionalOpenSSL,
                encryption_algorithm=serialization.NoEncryption()
            ))
            
        with open(cert_path, "wb") as f:
            f.write(cert.public_bytes(serialization.Encoding.PEM))
            
        return cert_path, key_path
    except ImportError:
        safe_print("[!] Falta 'cryptography'. Instálalo con: pip install cryptography")
        return None, None
    except Exception as e:
        safe_print(f"[!] Error generando certificado: {e}")
        return None, None

def get_public_ip():
    try:
        return urllib.request.urlopen('https://ident.me', timeout=3).read().decode('utf8')
    except:
        return None

def get_drives():
    drives = []
    if platform.system() == "Windows":
        for letter in string.ascii_uppercase:
            drive = f"{letter}:\\"
            if os.path.exists(drive):
                drives.append(drive)
    else:
        drives.append("/")
    return drives

def is_safe_path(path):
    """Valida que la ruta esté dentro de las unidades permitidas y resuelve '..'"""
    try:
        # Convertir a absoluta para resolver ../
        absolute_path = os.path.abspath(path)
        drives = get_drives()
        
        # Verificar si comienza con alguna de las unidades permitidas
        for drive in drives:
            # En Windows abspath devuelve C:\ruta pero drives puede ser C:\
            drive_abs = os.path.abspath(drive)
            if absolute_path.upper().startswith(drive_abs.upper()):
                return True
                
        # Si la ruta es exactamente una de las unidades (ej: C:), también es válida
        # Esto es un fallback por si abspath difiere ligeramente
        return False
    except Exception:
        return False

# --- HANDLER ---

class UniversalHandler(http.server.SimpleHTTPRequestHandler):
    def send_security_headers(self):
        """Añade cabeceras de seguridad fundamentales a todas las respuestas."""
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self' 'unsafe-inline' https://cdnjs.cloudflare.com; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src 'self' https://fonts.gstatic.com; img-src 'self' data:; frame-ancestors 'none';")
        self.send_header("X-XSS-Protection", "1; mode=block")

    def check_auth(self):
        """Verifica si el usuario tiene una sesión activa o un token válido."""
        # 1. Verificar token en la URL (para visores externos)
        parsed_path = urllib.parse.urlparse(self.path)
        query = urllib.parse.parse_qs(parsed_path.query)
        
        token = query.get('token', [None])[0]
        if token == VIEWER_TOKEN:
            return True

        # 2. Verificar Sesión mediante Cookie
        cookie_header = self.headers.get('Cookie')
        if cookie_header:
            cookie = http.cookies.SimpleCookie(cookie_header)
            if 'session_id' in cookie:
                s_id = cookie['session_id'].value
                if s_id in ACTIVE_SESSIONS:
                    if time.time() < ACTIVE_SESSIONS[s_id]:
                        # Limpiar sesiones expiradas de paso
                        expired = [k for k, v in ACTIVE_SESSIONS.items() if v <= time.time()]
                        for k in expired:
                            del ACTIVE_SESSIONS[k]
                        return True
                    else:
                        del ACTIVE_SESSIONS[s_id]
        
        # Permitir el POST de login para procesarlo
        if self.path == "/login" and self.command == "POST":
            return True
            
        self.render_login_page()
        return False

    def render_login_page(self, error_type=None):
        self.send_response(200)
        self.send_header("Content-type", "text/html; charset=utf-8")
        self.send_security_headers()
        self.end_headers()
        
        msg = "💡 <b>Portal Privado</b>"
        if error_type == "locked":
            msg = "🚫 <b>Demasiados intentos.</b> Espera unos minutos."
        elif error_type == "error":
            msg = "❌ <b>Contraseña incorrecta.</b>"

        html = f"""
        <html><head><meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Login - Portal</title>
        {self.get_common_css()}
        {self.get_common_js()}
        </head>
        <body style="display:flex; align-items:center; justify-content:center; height:100vh; margin:0;" onload="initTheme()">
            <div class="card" style="padding:40px; text-align:center; width:90%; max-width:400px;">
                <div style="font-size:50px; margin-bottom:20px;">🔒</div>
                <h2 style="margin-bottom:20px;">Portal Protegido</h2>
                <p style="margin-bottom:20px; color:var(--text); opacity:0.8; font-size:14px;">
                    {msg}
                </p>
                <form action="/login" method="POST">
                    <input type="password" name="pw" placeholder="Introduce la contraseña" 
                           style="width:100%; padding:15px; border-radius:8px; border:1px solid var(--border); margin-bottom:10px; font-size:16px; outline:none; background:var(--bg); color:var(--text);" required>
                    <button type="submit" class="btn">Desbloquear</button>
                </form>
            </div>
        </body></html>
        """
        self.wfile.write(html.encode('utf-8'))

    def do_GET(self):
        if not self.check_auth(): return
        parsed_path = urllib.parse.urlparse(self.path)
        query = urllib.parse.parse_qs(parsed_path.query)
        target_path = query.get('p', [None])[0]
        
        if not target_path:
            self.send_response(200)
            self.send_header("Content-type", "text/html; charset=utf-8")
            self.send_security_headers()
            self.end_headers()
            self.wfile.write(self.render_drive_selector().encode('utf-8'))
            return

        target_path = urllib.parse.unquote(target_path)
        
        # VALIDACIÓN DE RUTA
        if not is_safe_path(target_path):
             self.send_error(403, "Acceso denegado: Ruta no permitida o insegura.")
             return
        
        # Detectar solicitud de ZIP
        is_zip_request = query.get('zip', ['0'])[0] == '1'

        if os.path.isdir(target_path):
            if is_zip_request:
                self.serve_zip(target_path)
            else:
                self.send_response(200)
                self.send_header("Content-type", "text/html; charset=utf-8")
                self.send_security_headers()
                self.end_headers()
                self.wfile.write(self.render_explorer(target_path).encode('utf-8'))
        elif os.path.isfile(target_path):
            self.serve_file(target_path)
        else:
            self.send_error(404, "Ruta no encontrada")

    def do_POST(self):
        global PASSWORD_HASH
        client_ip = self.client_address[0]
        now = time.time()

        if self.path == "/login":
            # Verificar Bloqueo por IP
            if client_ip in LOGIN_ATTEMPTS:
                if now < LOGIN_ATTEMPTS[client_ip]['block_until']:
                    self.render_login_page(error_type="locked")
                    return
            
            length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(length)
            data = urllib.parse.parse_qs(body.decode('utf-8', errors='replace'))
            pw = data.get('pw', [''])[0]
            
            if verify_password(pw, PASSWORD_HASH):
                if not PASSWORD_HASH.startswith("pbkdf2:"):
                    new_hash = hash_password(pw)
                    CONF["PASSWORD_HASH"] = new_hash
                    PASSWORD_HASH = new_hash
                    try:
                        with open(CONFIG_FILE, 'w') as f:
                            json.dump(CONF, f, indent=4)
                    except Exception as e:
                        logger.warning(f"No se pudo guardar el hash actualizado: {e}")

                # Resetear intentos fallidos
                if client_ip in LOGIN_ATTEMPTS: del LOGIN_ATTEMPTS[client_ip]
                
                # Crear sesión temporal (volátil)
                session_id = str(uuid.uuid4())
                ACTIVE_SESSIONS[session_id] = now + (24 * 3600) # 24 horas
                
                self.send_response(303)
                self.send_header("Set-Cookie", f"session_id={session_id}; Path=/; HttpOnly; SameSite=Lax; Max-Age=86400")
                self.send_header("Location", "/")
                self.send_security_headers()
                self.end_headers()
            else:
                # Registrar Intento Fallido
                if client_ip not in LOGIN_ATTEMPTS:
                    LOGIN_ATTEMPTS[client_ip] = {'count': 0, 'block_until': 0}
                
                LOGIN_ATTEMPTS[client_ip]['count'] += 1
                if LOGIN_ATTEMPTS[client_ip]['count'] >= 5:
                    LOGIN_ATTEMPTS[client_ip]['block_until'] = now + 300 # 5 min bloqueo
                    self.render_login_page(error_type="locked")
                else:
                    self.render_login_page(error_type="error")
            return

        if not self.check_auth(): return
        
        parsed_path = urllib.parse.urlparse(self.path)
        query = urllib.parse.parse_qs(parsed_path.query)
        target_dir = query.get('p', [os.getcwd()])[0]
        target_dir = urllib.parse.unquote(target_dir)

        # VALIDACIÓN DE RUTA
        if not is_safe_path(target_dir):
             self.send_error(403, "Acceso denegado: Ruta no permitida o insegura.")
             return

        # 1. Verificar tamaño de subida antes de procesar
        content_length = int(self.headers.get('Content-Length', 0))
        if content_length > MAX_UPLOAD_SIZE:
            self.send_error(413, f"Archivo demasiado grande. Máximo permitido: {MAX_UPLOAD_SIZE // (1024*1024)}MB")
            return

        try:
            form = cgi.FieldStorage(
                fp=self.rfile,
                headers=self.headers,
                environ={'REQUEST_METHOD': 'POST', 'CONTENT_TYPE': self.headers['Content-Type']}
            )
            
            uploaded = []
            failed = []

            # Soportar múltiples archivos con el mismo campo "file"
            file_items = form["file"] if "file" in form else []
            if not isinstance(file_items, list):
                file_items = [file_items]

            for file_item in file_items:
                if file_item.filename:
                    fn = os.path.basename(file_item.filename)
                    dest = os.path.join(target_dir, fn)
                    CHUNK_SIZE = 1 * 1024 * 1024 # 1MB
                    try:
                        with open(dest, 'wb') as f:
                            while True:
                                chunk = file_item.file.read(CHUNK_SIZE)
                                if not chunk:
                                    break
                                f.write(chunk)
                        uploaded.append(fn)
                        logger.info(f"Archivo subido: {dest}")
                    except Exception as e:
                        failed.append(fn)
                        logger.warning(f"Error subiendo {fn}: {e}")

            if uploaded and not failed:
                if len(uploaded) == 1:
                    message = f"✅ ¡{uploaded[0]} subido con éxito!"
                else:
                    message = f"✅ ¡{len(uploaded)} archivos subidos con éxito!"
            elif uploaded and failed:
                message = f"⚠️ {len(uploaded)} subidos, {len(failed)} fallaron: {', '.join(failed)}"
            elif failed:
                message = f"❌ Error al subir: {', '.join(failed)}"
            else:
                message = "⚠️ No se seleccionó ningún archivo."
        except Exception as e:
            logger.error(f"Error en upload: {e}")
            message = f"❌ Error: {str(e)}"

        self.send_response(200)
        self.send_header("Content-type", "text/html; charset=utf-8")
        self.send_security_headers()
        self.end_headers()
        self.wfile.write(self.render_msg(message, target_dir).encode('utf-8'))
        
    def do_OPTIONS(self):
        self.send_response(200, "ok")
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header("Access-Control-Allow-Headers", "X-Requested-With, Content-Type, ngrok-skip-browser-warning")
        self.end_headers()

    def serve_file(self, path):
        try:
            # Obtener el tipo de contenido basado en la extensión
            content_type, _ = mimetypes.guess_type(path)
            if not content_type:
                content_type = "application/octet-stream"
            
            # Verificar si se solicita vista previa (inline)
            parsed_url = urllib.parse.urlparse(self.path)
            query = urllib.parse.parse_qs(parsed_url.query)
            is_inline = query.get('inline', ['0'])[0] == '1'
            
            CHUNK_SIZE = 1 * 1024 * 1024 # 1MB
            with open(path, 'rb') as f:
                self.send_response(200)
                self.send_header("Content-Type", content_type)
                
                # Si es inline, permitimos que el navegador lo muestre. 
                # Si no, forzamos la descarga (attachment).
                disposition = "inline" if is_inline else f'attachment; filename="{os.path.basename(path)}"'
                
                self.send_header("Content-Disposition", disposition)
                self.send_header("Content-Length", str(os.path.getsize(path)))
                self.send_header("ngrok-skip-browser-warning", "any")
                # CORS total para visores externos
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Access-Control-Allow-Headers", "*")
                self.send_header("Access-Control-Allow-Methods", "*")
                self.send_security_headers()
                self.end_headers()
                
                # Streaming en bloques de 1MB
                while True:
                    chunk = f.read(CHUNK_SIZE)
                    if not chunk:
                        break
                    self.wfile.write(chunk)
        except Exception as e:
            logger.warning(f"serve_file error en {path}: {e}")
            self.send_error(403, "Acceso denegado")

    def serve_zip(self, folder_path):
        """Comprime una carpeta y la sirve como descarga ZIP."""
        try:
            folder_name = os.path.basename(folder_path.rstrip(os.sep)) or "carpeta"
            zip_filename = f"{folder_name}.zip"
            
            # Crear un archivo temporal para el ZIP
            with tempfile.NamedTemporaryFile(delete=False, suffix=".zip") as tmp:
                tmp_path = tmp.name
            
            with zipfile.ZipFile(tmp_path, 'w', zipfile.ZIP_DEFLATED) as zf:
                for root, dirs, files in os.walk(folder_path):
                    for file in files:
                        file_path = os.path.join(root, file)
                        # Calcular ruta relativa dentro del ZIP
                        arcname = os.path.relpath(file_path, folder_path)
                        zf.write(file_path, arcname)
            
            # Servir el archivo en bloques (Streaming)
            CHUNK_SIZE = 1 * 1024 * 1024 # 1MB
            self.send_response(200)
            self.send_header("Content-Type", "application/zip")
            self.send_header("Content-Disposition", f'attachment; filename="{zip_filename}"')
            self.send_header("Content-Length", str(os.path.getsize(tmp_path)))
            self.send_security_headers()
            self.end_headers()

            with open(tmp_path, 'rb') as f:
                while True:
                    chunk = f.read(CHUNK_SIZE)
                    if not chunk:
                        break
                    self.wfile.write(chunk)
            
            # Limpiar temporal
            os.remove(tmp_path)
            
        except Exception as e:
            logger.error(f"serve_zip error: {e}")
            self.send_error(500, f"Error al crear ZIP: {e}")

    def get_common_css(self):
        return """
        <style>
            @import url('https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@300;400;500;600;700;800&display=swap');
            :root { 
                --primary: #1c1c1e; 
                --accent: #5856D6;
                --gradient: linear-gradient(135deg, #1c1c1e 0%, #444 100%);
                --bg: #f2f2F7; 
                --surface: rgba(255, 255, 255, 0.85); 
                --text: #1C1C1E; 
                --text-secondary: #8E8E93;
                --border: rgba(0, 0, 0, 0.08);
                --item-hover: rgba(0, 0, 0, 0.04);
                --shadow-sm: 0 4px 12px rgba(0,0,0,0.03);
                --shadow-lg: 0 20px 40px rgba(0,0,0,0.06);
            }
            body.dark { 
                --bg: #000000; 
                --surface: rgba(28, 28, 30, 0.9); 
                --text: #F2F2F7; 
                --text-secondary: #8E8E93;
                --border: rgba(255, 255, 255, 0.1);
                --item-hover: rgba(255, 255, 255, 0.08);
                --shadow-sm: 0 4px 12px rgba(0,0,0,0.2);
                --shadow-lg: 0 20px 40px rgba(0,0,0,0.4);
            }
            body { 
                font-family: 'Plus Jakarta Sans', -apple-system, sans-serif; 
                background: var(--bg); color: var(--text); margin: 0; padding: 0; 
                transition: all 0.4s ease; line-height: 1.5;
            }
            a { color: inherit; text-decoration: none; }
            
            .header { 
                background: var(--surface); backdrop-filter: blur(20px); -webkit-backdrop-filter: blur(20px);
                position: sticky; top: 0; z-index: 1000; padding: 12px 24px;
                display: flex; align-items: center; justify-content: space-between;
                border-bottom: 1px solid var(--border);
            }
            .header h1 { font-size: 1.1rem; font-weight: 800; letter-spacing: -0.5px; margin: 0; flex: 1; text-align: center; }
            .theme-toggle { background: none; border: none; font-size: 20px; cursor: pointer; padding: 5px; }

            .container { max-width: 900px; margin: 0 auto; padding: 30px 20px; }
            
            .card { 
                background: var(--surface); border: 1px solid var(--border); border-radius: 24px; 
                box-shadow: var(--shadow-sm); overflow: hidden; margin-bottom: 24px;
            }

            .drive-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 15px; margin-top: 15px; }
            .drive-card { 
                background: var(--surface); border: 1px solid var(--border); padding: 25px; 
                border-radius: 20px; text-align: center; transition: 0.3s; color: var(--text);
            }
            .drive-card:hover { transform: translateY(-3px); box-shadow: var(--shadow-lg); background: var(--item-hover); }

            .upload-box { 
                background: var(--gradient); color: white; border-radius: 28px; padding: 35px; 
                text-align: center; margin-bottom: 30px; box-shadow: 0 10px 30px rgba(0,0,0,0.1);
            }
            .upload-box h3 { font-size: 1.3rem; font-weight: 800; margin: 0 0 20px 0; }
            
            .btn { 
                padding: 14px 24px; border-radius: 16px; font-weight: 700; border: none; cursor: pointer;
                transition: all 0.2s; font-size: 0.95rem; background: var(--primary); color: white;
            }
            .btn:active { transform: scale(0.97); }

            .list-item { 
                display: flex; align-items: center; padding: 12px 18px; 
                border-bottom: 1px solid var(--border); transition: 0.2s;
            }
            .list-item:hover { background: var(--item-hover); }
            .list-item:last-child { border-bottom: none; }
            
            .name-link { flex: 1; display: flex; align-items: center; min-width: 0; overflow: hidden; }
            .icon { font-size: 24px; margin-right: 15px; flex-shrink: 0; }
            .name { flex: 1; font-weight: 600; font-size: 0.95rem; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; padding-right: 10px; }
            .actions { display: flex; align-items: center; flex-shrink: 0; }
            .size { color: var(--text-secondary); font-size: 0.8rem; font-weight: 500; margin-left: 10px; }
            
            .back-link { display: flex; align-items: center; padding: 15px 20px; border-bottom: 1px solid var(--border); font-weight: bold; color: var(--accent); }

            .controls { margin-bottom: 25px; }
            .search-box input { 
                width: 100%; box-sizing: border-box; background: var(--surface); border: 1px solid var(--border); 
                padding: 14px 20px; border-radius: 18px; font-size: 0.95rem; color: var(--text); outline: none;
            }
            .sort-chips { display: flex; gap: 8px; overflow-x: auto; padding-bottom: 10px; flex-wrap: wrap; }
            .chip { 
                padding: 8px 16px; border-radius: 12px; background: var(--surface); 
                border: 1px solid var(--border); font-size: 0.8rem; font-weight: 600; cursor: pointer; white-space: nowrap;
            }
            .chip.active { background: var(--accent); color: #fff; border-color: var(--accent); }
            
            .breadcrumbs { padding: 10px 0; font-size: 0.85rem; font-weight: 600; margin-bottom: 15px; color: var(--accent); }

            /* MODAL STYLES */
            .modal { 
                display: none; position: fixed; z-index: 2000; left: 0; top: 0; width: 100%; height: 100%; 
                background-color: rgba(0,0,0,0.8); backdrop-filter: blur(5px);
            }
            .modal-content { 
                position: relative; background-color: var(--bg); margin: 2% auto; padding: 0; 
                width: 90%; max-width: 1000px; height: 90vh; border-radius: 20px; overflow: hidden;
                display: flex; flex-direction: column; box-shadow: 0 25px 50px rgba(0,0,0,0.5);
            }
            .modal-header { padding: 15px 20px; border-bottom: 1px solid var(--border); display: flex; align-items: center; justify-content: space-between; }
            .modal-body { flex: 1; overflow: auto; padding: 0; display: flex; flex-direction: column; align-items: center; justify-content: center; background: #333; }
            .modal-body img { max-width: 100%; max-height: 100%; object-fit: contain; }
            .modal-body pre { background: white; color: black; padding: 20px; width: 100%; box-sizing: border-box; margin: 0; font-family: monospace; white-space: pre-wrap; overflow-x: auto; }
            .close { color: var(--text); font-size: 28px; font-weight: bold; cursor: pointer; padding: 0 10px; }
            .close:hover { color: var(--accent); }

            @keyframes fadeIn { from { opacity: 0; transform: translateY(10px); } to { opacity: 1; transform: translateY(0); } }
            .container > * { animation: fadeIn 0.4s ease forwards; }
        </style>
        """

    def get_common_js(self):
        js_code = """
        <!-- Librerías para renderizado local (Infalible) -->
        <script src="https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.min.js"></script>
        <script src="https://cdnjs.cloudflare.com/ajax/libs/mammoth/1.6.0/mammoth.browser.min.js"></script>
        <script src="https://cdnjs.cloudflare.com/ajax/libs/xlsx/0.18.5/xlsx.full.min.js"></script>
        <script>
            // Configurar worker de PDF.js
            try {
                pdfjsLib.GlobalWorkerOptions.workerSrc = 'https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.worker.min.js';
            } catch(e) { console.error("Error cargando PDF.js worker", e); }
        </script>

        <script>
            const S_TOKEN = "PASSWORD_HERE";
            function toggleTheme() {
                const body = document.body;
                body.classList.toggle('dark');
                const isDark = body.classList.contains('dark');
                localStorage.setItem('theme', isDark ? 'dark' : 'light');
                updateThemeIcon();
            }

            function initTheme() {
                const savedTheme = localStorage.getItem('theme');
                if (savedTheme === 'dark') {
                    document.body.classList.add('dark');
                }
                updateThemeIcon();
            }

            function updateThemeIcon() {
                const btn = document.getElementById('theme-btn');
                if (btn) {
                    const isDark = document.body.classList.contains('dark');
                    btn.innerHTML = isDark ? '🌙' : '☀️';
                }
            }
            
            function previewFile(url, type, name) {
                const modal = document.getElementById('previewModal');
                const modalBody = document.getElementById('modalBody');
                const modalTitle = document.getElementById('modalTitle');
                
                modalTitle.innerText = name;
                modalBody.innerHTML = '<div style="color:white; padding:20px; text-align:center;">Cargando visor...</div>';
                modal.style.display = "block";
                
                const previewUrl = url + "&inline=1";
                const isLocal = window.location.hostname === 'localhost' || 
                                window.location.hostname === '127.0.0.1' || 
                                window.location.hostname.startsWith('192.168.') ||
                                window.location.hostname.startsWith('10.');

                // El token permite que Google Viewer pase el login
                const authParams = `&token=${S_TOKEN}&ngrok-skip-browser-warning=1`;
                
                // Normalizar URL: convertir contrabarras en barras y asegurar codificación completa
                const fullPath = window.location.origin + previewUrl + authParams;
                // Las barras ya han sido normalizadas en el servidor.
                const publicUrl = fullPath;
                
                if (type === 'image') {
                    modalBody.innerHTML = `<img src="${previewUrl}" alt="${name}">`;
                } else if (type === 'pdf') {
                    // Renderizado PDF nativo con PDF.js (Canvas)
                    modalBody.innerHTML = `
                        <div id="pdf-container" style="width:100%; height:100%; overflow:auto; background:#333; display:flex; flex-direction:column; align-items:center;">
                            <div id="pdf-controls" style="position:sticky; top:0; background:rgba(0,0,0,0.8); color:white; padding:10px; border-radius:10px; margin-bottom:10px; z-index:100;">
                                <button onclick="prevPage()" class="btn" style="width:auto; padding:5px 10px;">⬅️</button>
                                <span id="page-num">1</span> / <span id="page-count">--</span>
                                <button onclick="nextPage()" class="btn" style="width:auto; padding:5px 10px;">➡️</button>
                            </div>
                            <canvas id="the-canvas" style="border:1px solid black; max-width:100%;"></canvas>
                        </div>`;
                    
                    renderPDF(publicUrl);

                } else if (type === 'office') {
                    // Detectar extensión
                    const lowerUrl = publicUrl.toLowerCase();
                    const isDocx = lowerUrl.includes('.docx');
                    const isXls = lowerUrl.includes('.xls') || lowerUrl.includes('.xlsx');
                    
                    if (isDocx) {
                        // Renderizado Word nativo con Mammoth.js
                        fetch(publicUrl)
                        .then(response => {
                            if (!response.ok) throw new Error("Error " + response.status);
                            return response.arrayBuffer();
                        })
                        .then(arrayBuffer => mammoth.convertToHtml({arrayBuffer: arrayBuffer}))
                        .then(result => {
                            modalBody.innerHTML = `
                                <div style="background:white; color:black; padding:40px; text-align:left; max-width:800px; margin:auto; min-height:100%;">
                                    ${result.value}
                                </div>`;
                        })
                        .catch(err => {
                            console.error(err);
                            renderExternalOffice(publicUrl, modalBody, previewUrl);
                        });
                    } else if (isXls) {
                        // Renderizado Excel con SheetJS
                        fetch(publicUrl)
                        .then(response => {
                            if (!response.ok) throw new Error("Error " + response.status);
                            return response.arrayBuffer();
                        })
                        .then(data => {
                            const workbook = XLSX.read(data, {type: 'array'});
                            const firstSheetName = workbook.SheetNames[0];
                            const worksheet = workbook.Sheets[firstSheetName];
                            const html = XLSX.utils.sheet_to_html(worksheet);
                            modalBody.innerHTML = `
                                <div style="background:white; color:black; padding:20px; overflow:auto; max-width:100%; max-height:100%;">
                                    <style>table { border-collapse: collapse; width: 100%; } td, th { border: 1px solid #ddd; padding: 8px; text-align: left; } th { background-color: #f2f2f2; }</style>
                                    ${html}
                                </div>`;
                        })
                        .catch(err => {
                            console.error(err);
                            renderExternalOffice(publicUrl, modalBody, previewUrl);
                        });
                    } else {
                        // Formato no soportado localmente (.doc, .ppt, etc)
                        modalBody.innerHTML = `
                            <div style="color:white; padding:40px; text-align:center;">
                                <div style="font-size:60px; margin-bottom:20px;">📄</div>
                                <h3>Formato antiguo o complejo</h3>
                                <p>Este archivo (<b>${name}</b>) no se puede previsualizar en el navegador por seguridad.</p>
                                <p style="opacity:0.7;">Por favor, descárgalo para abrirlo con tu aplicación de escritorio.</p>
                                <div style="margin-top:30px;">
                                    <a href="${previewUrl}" class="btn" style="width:auto; padding:15px 30px; font-size:16px; background:var(--primary);">⬇️ Descargar Archivo</a>
                                </div>
                            </div>`;
                    }
                } else if (type === 'text') {
                    fetch(publicUrl)
                        .then(response => response.text())
                        .then(text => {
                            modalBody.innerHTML = `<pre>${escapeHtml(text)}</pre>`;
                        })
                        .catch(err => {
                            modalBody.innerHTML = `<div style="color:red; padding:20px;">Error al cargar: ${err}</div>`;
                        });
                }
            }

            let pdfDoc = null,
                pageNum = 1,
                pageRendering = false,
                pageNumPending = null;

            function renderPDF(url) {
                pdfjsLib.getDocument(url).promise.then(function(pdfDoc_) {
                    pdfDoc = pdfDoc_;
                    document.getElementById('page-count').textContent = pdfDoc.numPages;
                    renderPage(pageNum);
                });
            }

            function renderPage(num) {
                pageRendering = true;
                pdfDoc.getPage(num).then(function(page) {
                    var scale = 1.5;
                    var viewport = page.getViewport({scale: scale});
                    var canvas = document.getElementById('the-canvas');
                    var context = canvas.getContext('2d');
                    canvas.height = viewport.height;
                    canvas.width = viewport.width;

                    var renderContext = {
                        canvasContext: context,
                        viewport: viewport
                    };
                    var renderTask = page.render(renderContext);

                    renderTask.promise.then(function() {
                        pageRendering = false;
                        if (pageNumPending !== null) {
                            renderPage(pageNumPending);
                            pageNumPending = null;
                        }
                    });
                });
                document.getElementById('page-num').textContent = num;
            }

            function queueRenderPage(num) {
                if (pageRendering) {
                    pageNumPending = num;
                } else {
                    renderPage(num);
                }
            }

            function prevPage() {
                if (pageNum <= 1) return;
                pageNum--;
                queueRenderPage(pageNum);
            }

            function nextPage() {
                if (pdfDoc && pageNum >= pdfDoc.numPages) return;
                pageNum++;
                queueRenderPage(pageNum);
            }

            function closePreview() {
                const modal = document.getElementById('previewModal');
                modal.style.display = "none";
                document.getElementById('modalBody').innerHTML = "";
                pdfDoc = null;
                pageNum = 1;
            }


            function escapeHtml(text) {
                const div = document.createElement('div');
                div.textContent = text;
                return div.innerHTML;
            }

            let ALL_ITEMS = []; 
            let VISIBLE_ITEMS = [];
            let currentBatch = 0;
            const BATCH_SIZE = 50;

            function initExplorer(itemsJson) {
                // Filtrar nulos si los hubiera por errores de try/except en el server
                ALL_ITEMS = itemsJson.filter(i => i !== null);
                VISIBLE_ITEMS = [...ALL_ITEMS];
                renderBatch(true);
                
                window.onscroll = function() {
                    const threshold = 300;
                    if ((window.innerHeight + window.scrollY) >= document.body.offsetHeight - threshold) {
                        renderBatch(false);
                    }
                };
            }

            function renderBatch(reset) {
                const container = document.getElementById('files-container');
                if (reset) {
                    container.innerHTML = '';
                    currentBatch = 0;
                }
                
                const start = currentBatch * BATCH_SIZE;
                const end = start + BATCH_SIZE;
                const batch = VISIBLE_ITEMS.slice(start, end);
                
                if (batch.length === 0 && reset) {
                    document.getElementById('no-results').style.display = 'block';
                } else {
                    document.getElementById('no-results').style.display = 'none';
                }

                batch.forEach(item => {
                    const div = document.createElement('div');
                    div.className = 'list-item';
                    div.dataset.category = item.cat;
                    
                    div.innerHTML = `
                        <a href="${item.url}" class="name-link">
                            <span class="icon">${item.icon}</span>
                            <span class="name">${item.name}</span>
                        </a>
                        <div class="actions">
                            <span class="size">${item.size_str}</span>
                            ${item.preview_btn || ''}
                        </div>
                    `;
                    container.appendChild(div);
                });
                
                currentBatch++;
            }

            function filterFiles() {
                const query = document.getElementById('search-input').value.toLowerCase();
                VISIBLE_ITEMS = ALL_ITEMS.filter(item => 
                    item.name.toLowerCase().includes(query)
                );
                renderBatch(true);
            }

            function sortFiles(criteria) {
                const chips = document.querySelectorAll('.chip');
                // Quitar active de los chips de ordenación
                chips.forEach(c => {
                    if (c.onclick && c.onclick.toString().includes('sortFiles')) {
                        c.classList.remove('active');
                    }
                });
                if (event) event.target.classList.add('active');

                const folders = VISIBLE_ITEMS.filter(i => i.cat === 'folder');
                const files = VISIBLE_ITEMS.filter(i => i.cat !== 'folder');

                const sortFn = (a, b) => {
                    if (criteria === 'name') return a.name.localeCompare(b.name);
                    if (criteria === 'date') return b.mtime - a.mtime;
                    if (criteria === 'size') return b.size - a.size;
                };

                files.sort(sortFn);
                VISIBLE_ITEMS = [...folders, ...files];
                renderBatch(true);
            }

            function filterByCategory(category) {
                const chips = document.querySelectorAll('.chip');
                // Quitar active de los chips de categoría
                chips.forEach(c => {
                    if (c.onclick && c.onclick.toString().includes('filterByCategory')) {
                        c.classList.remove('active');
                    }
                });
                if (event) event.target.classList.add('active');

                const query = document.getElementById('search-input').value.toLowerCase();
                VISIBLE_ITEMS = ALL_ITEMS.filter(item => {
                    const matchCat = (category === 'all' || item.cat === category);
                    const matchSearch = item.name.toLowerCase().includes(query);
                    return matchCat && matchSearch;
                });
                renderBatch(true);
            }

            window.onclick = function(event) {
                const modal = document.getElementById('previewModal');
                if (event.target == modal) {
                    closePreview();
                }
            }

            function uploadFile() {
                const fileInput = document.getElementById('file-upload');
                const files = Array.from(fileInput.files);
                if (files.length === 0) {
                    alert("Por favor seleccioná al menos un archivo.");
                    return;
                }

                const progressContainer = document.getElementById('progress-container');
                const progressBar = document.getElementById('progress-bar');
                const uploadBtn = document.getElementById('upload-btn');
                const statusLabel = document.getElementById('upload-status');

                uploadBtn.disabled = true;
                progressContainer.style.display = 'block';
                progressBar.style.backgroundColor = 'var(--accent)';

                const urlParams = new URLSearchParams(window.location.search);
                const path = urlParams.get('p') || '';
                const uploadUrl = '/?p=' + encodeURIComponent(path);

                let completed = 0;
                let failed = 0;

                function uploadNext(index) {
                    if (index >= files.length) {
                        // Todos terminados
                        const total = files.length;
                        if (failed === 0) {
                            uploadBtn.innerText = total === 1 ? "¡Subida completada!" : `¡${total} archivos subidos!`;
                            progressBar.style.backgroundColor = "#4CAF50";
                            progressBar.style.width = "100%";
                            progressBar.textContent = "100%";
                        } else {
                            uploadBtn.innerText = `${completed} OK, ${failed} fallaron`;
                            progressBar.style.backgroundColor = "#FF9500";
                        }
                        if (statusLabel) statusLabel.textContent = '';
                        setTimeout(() => window.location.reload(), 800);
                        return;
                    }

                    const file = files[index];
                    if (statusLabel) {
                        statusLabel.textContent = files.length > 1
                            ? `Subiendo ${index + 1}/${files.length}: ${file.name}`
                            : `Subiendo: ${file.name}`;
                    }

                    const formData = new FormData();
                    formData.append('file', file);

                    const xhr = new XMLHttpRequest();

                    xhr.upload.onprogress = function(event) {
                        if (event.lengthComputable) {
                            // Progreso total considerando archivos previos
                            const fileProgress = event.loaded / event.total;
                            const totalPercent = Math.round(((index + fileProgress) / files.length) * 100);
                            progressBar.style.width = totalPercent + '%';
                            progressBar.textContent = totalPercent + '%';
                            uploadBtn.innerText = `Subiendo... ${totalPercent}%`;
                        }
                    };

                    xhr.onload = function() {
                        if (xhr.status === 200) {
                            completed++;
                        } else {
                            failed++;
                            console.error(`Error subiendo ${file.name}: HTTP ${xhr.status}`);
                        }
                        uploadNext(index + 1);
                    };

                    xhr.onerror = function() {
                        failed++;
                        console.error(`Error de red subiendo ${file.name}`);
                        uploadNext(index + 1);
                    };

                    xhr.open('POST', uploadUrl, true);
                    xhr.send(formData);
                }

                uploadNext(0);
            }
            
            if (document.readyState === 'loading') {
                document.addEventListener('DOMContentLoaded', initTheme);
            } else {
                initTheme();
            }
        </script>
        """
        return js_code.replace("PASSWORD_HERE", VIEWER_TOKEN)

    def get_quick_access(self):
        home = os.path.expanduser("~")
        shortcuts = []
        paths = {
            "🖥️ Escritorio": os.path.join(home, "Desktop"),
            "📥 Descargas": os.path.join(home, "Downloads"),
            "🖼️ Imágenes": os.path.join(home, "Pictures"),
            "🎬 Videos": os.path.join(home, "Videos"),
        }
        for name, path in paths.items():
            if os.path.exists(path):
                shortcuts.append((name, path))
        return shortcuts

    def render_drive_selector(self):
        drives = get_drives()
        shortcuts = self.get_quick_access()
        html = f"""
        <html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
        {self.get_common_css()}
        {self.get_common_js()}
        </head>
        <body onload="initTheme()">
            <div class="header">
                <button id="theme-btn" class="theme-toggle" onclick="toggleTheme()" title="Modo Oscuro/Claro">☀️</button>
                <h1>🗂️ Mi Computadora</h1>
                <div style="width:40px;"></div> <!-- Spacer for centering -->
            </div>
            <div class="container">
                <h3 style="margin-top:0; color:#555;">🚀 Acceso Rápido</h3>
                <div class="drive-grid" style="margin-bottom:30px;">
        """
        for name, path in shortcuts:
            url = f"/?p={urllib.parse.quote(path)}"
            icon, label = name.split(" ", 1)
            html += f"""
            <a href="{url}" class="drive-card">
                <div style="font-size:35px;">{icon}</div>
                <div style="font-weight:bold;margin-top:8px;font-size:14px;">{label}</div>
            </a>"""
        html += """
                </div>
                <h3 style="color:#555;">💾 Discos Locales</h3>
                <div class="drive-grid">
        """
        for d in drives:
            url = f"/?p={urllib.parse.quote(d)}"
            html += f"""
            <a href="{url}" class="drive-card" style="background:var(--drive-bg);">
                <div style="font-size:35px;">💿</div>
                <div style="font-weight:bold;margin-top:8px;font-size:14px;">Disco {d}</div>
            </a>"""
        html += "</div></div></body></html>"
        return html

    def render_explorer(self, path):
        try:
            items = os.listdir(path)
        except Exception:
            return "<html><body><h1>Acceso denegado</h1><a href='/'>Volver al inicio</a></body></html>"
        
        items.sort(key=lambda x: (not os.path.isdir(os.path.join(path, x)), x.lower()))
        parts = path.split(os.sep)
        b_html = '<a href="/">Inicio</a>'
        current_acc = ""
        for i, part in enumerate(parts):
            if not part: continue
            current_acc += part + os.sep
            b_html += f' > <a href="/?p={urllib.parse.quote(current_acc)}">{part}</a>'

        html = f"""
        <html><head>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Explorador</title>
            {self.get_common_css()}
            {self.get_common_js()}
        </head>
        <body onload="initTheme()">
            <div class="header">
                <button id="theme-btn" class="theme-toggle" onclick="toggleTheme()">☀️</button>
                <h1>{os.path.basename(path) or path}</h1>
                <div style="width:40px;"></div> <!-- Spacer -->
            </div>
            <div class="breadcrumbs">{b_html}</div>
            <div class="container">
                <div class="upload-box">
                    <h3>📤 Subir a esta carpeta</h3>
                    <div style="margin-bottom:15px;">
                        <input type="file" id="file-upload" name="file" multiple style="width:100%;">
                    </div>
                    <div id="upload-status" style="font-size:0.85rem; color:rgba(255,255,255,0.8); min-height:1.2em; margin-bottom:8px;"></div>
                    <button id="upload-btn" onclick="uploadFile()" class="btn">Subir al Servidor</button>
                    <div id="progress-container" class="progress-container">
                        <div id="progress-bar" class="progress-bar">0%</div>
                    </div>
                </div>

                <div class="controls">
                    <div class="search-box">
                        <input type="text" id="search-input" placeholder="Buscar por nombre o tipo..." onkeyup="filterFiles()">
                    </div>
                    <div class="sort-chips" style="margin-top:5px;">
                        <span class="chip active" onclick="sortFiles('name')">🔤 Nombre</span>
                        <span class="chip" onclick="sortFiles('date')">🕒 Recientes</span>
                        <span class="chip" onclick="sortFiles('size')">⚖️ Tamaño</span>
                    </div>
                    <div class="sort-chips" style="margin-top:5px; border-top:1px solid var(--border); padding-top:10px;">
                        <span class="chip active" onclick="filterByCategory('all')">Todo</span>
                        <span class="chip" onclick="filterByCategory('image')">🖼️ Fotos</span>
                        <span class="chip" onclick="filterByCategory('pdf')">📄 PDF</span>
                        <span class="chip" onclick="filterByCategory('office')">📝 Office</span>
                        <span class="chip" onclick="filterByCategory('text')">TXT</span>
                    </div>
                </div>

                <div class="card">
                    <div id="no-results" style="display:none; padding:40px; text-align:center; color:var(--text); opacity:0.6;">
                        No se encontraron archivos que coincidan.
                    </div>
                    <div id="files-container"></div>
                </div>
        """
        file_list = []
        if len(parts) > 1:
            parent_dir = os.path.dirname(path.rstrip(os.sep))
            parent_url = f"/?p={urllib.parse.quote(parent_dir)}"
            # El botón de "Subir nivel" se mantiene separado para que no se filtre
            html = html.replace('<div id="files-container"></div>', f'<a href="{parent_url}" class="back-link"><span class="icon">🔙</span><span class="name">.. (Subir nivel)</span></a><div id="files-container"></div>')

        for item in items:
            if item.startswith('.'): continue
            full = os.path.join(path, item)
            try:
                is_dir = os.path.isdir(full)
                icon = "📁" if is_dir else "📄"
                url_path = full.replace("\\", "/") 
                url = f"/?p={urllib.parse.quote(url_path)}"
                
                size_bytes = 0
                size_str = ""
                mtime = 0
                if not is_dir:
                    size_bytes = os.path.getsize(full)
                    size_str = self.format_size(size_bytes)
                    mtime = os.path.getmtime(full)
                else:
                    try: mtime = os.path.getmtime(full)
                    except Exception: pass

                # Categoría para filtro
                ext = os.path.splitext(full)[1].lower()
                cat = "other"
                if is_dir: cat = "folder"
                elif ext in ['.jpg', '.jpeg', '.png', '.gif', '.svg', '.webp']: cat = "image"
                elif ext == '.pdf': cat = "pdf"
                elif ext in ['.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx']: cat = "office"
                elif ext in ['.txt', '.py', '.js', '.css', '.html', '.json', '.md']: cat = "text"

                file_list.append({
                    "name": item,
                    "url": url,
                    "icon": icon,
                    "size": size_bytes,
                    "size_str": size_str,
                    "mtime": mtime,
                    "cat": cat,
                    "preview_btn": self.get_preview_button(full, item) if not is_dir else f'<a href="{url}&zip=1" style="text-decoration:none; font-size:20px; padding:15px;" title="Descargar como ZIP">📦</a>'
                })
            except Exception as e:
                logger.warning(f"Error procesando item '{item}': {e}")
                continue
        
        # Inyectar JSON de forma segura en un bloque script (para no romper el HTML con comillas)
        import json
        json_items = json.dumps(file_list)
        
        # Agregamos el modal y los cierres de etiquetas. Usamos f-string para inyectar json_items
        html += f"""
                </div>
            </div>
            <!-- Modal de Vista Previa -->
            <div id="previewModal" class="modal">
                <div class="modal-content">
                    <div class="modal-header">
                        <h3 id="modalTitle" style="margin:0; font-size:16px;">Vista Previa</h3>
                        <span class="close" onclick="closePreview()">&times;</span>
                    </div>
                    <div id="modalBody" class="modal-body"></div>
                </div>
            </div>
            <script>
                const FILE_DATA = {json_items};
                initTheme(); 
                initExplorer(FILE_DATA);
            </script>
        </body></html>
        """
        return html

    def get_preview_button(self, path, name):
        ext = os.path.splitext(path)[1].lower()
        type_map = {
            '.jpg': 'image', '.jpeg': 'image', '.png': 'image', '.gif': 'image', '.svg': 'image', '.webp': 'image',
            '.pdf': 'pdf',
            '.txt': 'text', '.py': 'text', '.js': 'text', '.css': 'text', '.html': 'text', '.json': 'text', '.md': 'text',
            '.doc': 'office', '.docx': 'office', '.xls': 'office', '.xlsx': 'office', '.ppt': 'office', '.pptx': 'office'
        }
        
        if ext in type_map:
            url = f"/?p={urllib.parse.quote(path)}"
            return f'<button onclick="previewFile(\'{url}\', \'{type_map[ext]}\', \'{name}\')" style="background:none; border:none; font-size:20px; cursor:pointer; padding:15px;" title="Vista rápida">👁️</button>'
        return ""

    def render_msg(self, msg, path):
        return f"""
        <html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
        {self.get_common_css()}
        {self.get_common_js()}
        </head>
        <body onload="initTheme()">
            <div class="container" style="text-align:center; padding-top:100px;">
                <div class="card" style="padding:40px;">
                    <div style="font-size:50px; margin-bottom:20px;">{msg.split()[0]}</div>
                    <h2>{msg}</h2>
                    <a href="/?p={urllib.parse.quote(path)}" class="btn" style="text-decoration:none; display:inline-block;">Volver a la carpeta</a>
                </div>
            </div>
        </body></html>
        """

    def format_size(self, size):
        for unit in ['B', 'KB', 'MB', 'GB']:
            if size < 1024: return f"{size:.1f} {unit}"
            size /= 1024
        return f"{size:.1f} TB"

# --- SERVER RUNNER ---

def run_server():
    port = BASE_PORT
    success = False
    httpd = None

    safe_print("\n" + "*"*20)
    safe_print("   PORTAL UNIVERSAL ACTIVADO")
    safe_print("*"*20)

    is_https = False
    for i in range(MAX_PORT_ATTEMPTS):
        try:
            socketserver.ThreadingTCPServer.allow_reuse_address = True
            httpd = socketserver.ThreadingTCPServer(("", port), UniversalHandler)
            
            cert_path, key_path = ensure_certificates()
            if cert_path and key_path:
                try:
                    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
                    context.load_cert_chain(certfile=cert_path, keyfile=key_path)
                    httpd.socket = context.wrap_socket(httpd.socket, server_side=True)
                    is_https = True
                except Exception as e:
                    safe_print(f"[!] TLS Error: {e}. Se usará HTTP.")
            
            success = True
            break
        except OSError as e:
            if e.errno in [10048, 98]:
                safe_print(f"Puerto {port} ocupado, intentando con {port + 1}...")
                port += 1
            else:
                raise e

    if not success:
        safe_print("No se pudo encontrar un puerto libre.")
        return

    ip_local = get_ip()
    protocol = "https" if is_https else "http"
    url_local = f"{protocol}://{ip_local}:{port}"
    url_final = url_local # Por defecto usamos la local

    # Intentar configurar NGROK si hay token
    if NGROK_TOKEN:
        try:
            from pyngrok import ngrok
            ngrok.set_auth_token(NGROK_TOKEN)
            
            # Configurar región si se especifica
            if NGROK_REGION:
                from pyngrok.conf import PyngrokConfig
                config = PyngrokConfig(region=NGROK_REGION)
            else:
                config = None

            # Si el local es HTTPS, debemos decírselo a ngrok
            addr = f"https://localhost:{port}" if is_https else port

            # Si hay dominio estático, lo usamos
            if NGROK_DOMAIN:
                public_url = ngrok.connect(addr, domain=NGROK_DOMAIN, pyngrok_config=config).public_url
            else:
                public_url = ngrok.connect(addr, pyngrok_config=config).public_url
            
            url_final = public_url
            safe_print(f"\n[!] TUNEL NGROK ACTIVADO:")
            safe_print(f"Link Publico: {public_url}")
        except ImportError:
            print("\n[!] Error: No se encontró 'pyngrok'.")
            print("   Para usar Internet (Ngrok), escribe esto en tu consola: pip install pyngrok")
        except Exception as e:
            print(f"\n[!] Error al iniciar Ngrok: {e}")

    safe_print(f"\nAcceso Local (WiFi): {url_local}")
    safe_print("\n--- CODIGO QR (LOCAL / WiFi) ---")
    try:
        qr_local = qrcode.QRCode(version=1, box_size=1, border=1)
        qr_local.add_data(url_local)
        qr_local.print_ascii()
    except Exception as e:
        safe_print(f"  (No se pudo mostrar el QR en consola: {e})")

    def show_qrs_gui(u_local, u_remote):
        root = tk.Tk()
        root.title("File Portal")
        root.geometry("400x650")
        root.configure(bg="#ffffff")
        root.attributes("-topmost", True)
        
        # Frame de Estilo con Sombra
        main_frame = tk.Frame(root, bg="#ffffff", padx=40, pady=40)
        main_frame.pack(expand=True, fill="both")
        
        def get_qr_img(data):
            qr = qrcode.QRCode(version=1, box_size=8, border=2)
            qr.add_data(data)
            qr.make(fit=True)
            img = qr.make_image(fill_color="#1C1C1E", back_color="#ffffff")
            img = img.resize((180, 180), Image.Resampling.LANCZOS)
            return ImageTk.PhotoImage(img)

        root.qr_images = []

        def copy_to_clipboard(text, label_widget):
            root.clipboard_clear()
            root.clipboard_append(text)
            original_text = label_widget.cget("text")
            label_widget.config(text="¡Copiado! ✅", fg="#34C759")
            root.after(2000, lambda: label_widget.config(text=original_text, fg="#8E8E93"))

        tk.Label(main_frame, text="Portal Activo", font=("Plus Jakarta Sans", 18, "bold"), bg="#ffffff", fg="#1C1C1E").pack(pady=(0, 30))

        # Local
        tk.Label(main_frame, text="WiFi Local", font=("Plus Jakarta Sans", 10, "bold"), bg="#ffffff", fg="#5856D6").pack()
        link_local = tk.Label(main_frame, text=u_local, font=("Plus Jakarta Sans", 9), bg="#ffffff", fg="#8E8E93", cursor="hand2")
        link_local.pack(pady=(0, 5))
        link_local.bind("<Button-1>", lambda e: copy_to_clipboard(u_local, link_local))
        
        img_local = get_qr_img(u_local)
        root.qr_images.append(img_local)
        tk.Label(main_frame, image=img_local, bg="white", highlightthickness=1, highlightbackground="#F2F2F7").pack(pady=(0, 20))

        # Remote
        if u_local != u_remote:
            tk.Label(main_frame, text="Internet Remoto", font=("Plus Jakarta Sans", 10, "bold"), bg="#ffffff", fg="#FF2D55").pack()
            link_remote = tk.Label(main_frame, text=u_remote, font=("Plus Jakarta Sans", 9), bg="#ffffff", fg="#8E8E93", cursor="hand2")
            link_remote.pack(pady=(0, 5))
            link_remote.bind("<Button-1>", lambda e: copy_to_clipboard(u_remote, link_remote))
            
            img_remote = get_qr_img(u_remote)
            root.qr_images.append(img_remote)
            tk.Label(main_frame, image=img_remote, bg="white", highlightthickness=1, highlightbackground="#F2F2F7").pack(pady=(0, 20))
        
        tk.Label(main_frame, text="Haz clic en el link para copiar", font=("Plus Jakarta Sans", 8, "italic"), bg="#ffffff", fg="#C7C7CC").pack(pady=(10, 0))
        tk.Label(main_frame, text="Mantén esta ventana abierta", font=("Plus Jakarta Sans", 8), bg="#ffffff", fg="#C7C7CC").pack(side="bottom")
        
        root.protocol("WM_DELETE_WINDOW", lambda: sys.exit(0))
        root.mainloop()

    # No redirigir stdout — usamos logging que ya maneja esto correctamente

    if url_final != url_local:
        # Mostrar QR en consola por si acaso
        try:
            qr_remoto = qrcode.QRCode(version=1, box_size=1, border=1)
            qr_remoto.add_data(url_final)
            qr_remoto.print_ascii()
        except Exception as e:
            logger.warning(f"No se pudo mostrar QR remoto: {e}")
    
    # Iniciar el servidor en un hilo secundario para que no bloquee la GUI
    threading.Thread(target=httpd.serve_forever, daemon=True).start()

    # --- AUTO-OPEN BROWSER ---
    def open_browser():
        time.sleep(1.5) # Esperar un poco a que el servidor este listo
        safe_print(f"\nAbriendo navegador en: {url_local}")
        webbrowser.open(url_local)

    if AUTO_OPEN_BROWSER:
        threading.Thread(target=open_browser, daemon=True).start()

    safe_print("\n" + "="*40)
    safe_print(f"Seguridad: Con contraseña")
    safe_print("Cierra la ventana de los QR para apagar el servidor.")

    try:
        # Iniciar la interfaz de QRs en el hilo principal
        show_qrs_gui(url_local, url_final)
    except KeyboardInterrupt:
        safe_print("\n[!] Apagando servidor...")
        if NGROK_TOKEN:
            try:
                from pyngrok import ngrok
                ngrok.disconnect(url_final)
                ngrok.kill()
            except Exception as e:
                logger.warning(f"Error cerrando ngrok: {e}")
        httpd.server_close()

if __name__ == "__main__":
    try:
        run_server()
    except Exception as e:
        print(f"\n[!] ERROR: {e}")
        import traceback
        traceback.print_exc()
        print("\n" + "!" * 40)
        input("Presiona ENTER para cerrar esta ventana...")
        sys.exit(1)
