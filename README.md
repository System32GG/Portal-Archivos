# 🗂️ Portal de Archivos Universal

Una herramienta potente y sencilla en Python para compartir archivos entre tu PC y otros dispositivos (Móviles, Tablets, otras PCs) a través de WiFi o Internet (vía Ngrok).

![Python Version](https://img.shields.io/badge/python-3.7%2B-blue)
![License](https://img.shields.io/badge/license-MIT-green)

## ✨ Características

- **Acceso Local & Remoto**: Comparte por WiFi local o usa el túnel de **Ngrok** para acceder desde cualquier lugar con datos móviles.
- **Conexión Cifrada (HTTPS)**: Todas las conexiones, tanto locales como remotas, viajan cifradas punto a punto para proteger tus datos.
- **Interfaz Moderna**: Diseño limpio y premium con **Modo Oscuro** automático.
- **Explorador Full**: Navega por tus discos locales, descarga carpetas completas como **ZIP**.
- **Seguridad Avanzada**: Acceso protegido por contraseña (hasheada con **PBKDF2** de alta resistencia).
- **Visor en Tiempo Real**: Previsualiza imágenes, PDFs, documentos de Office y archivos de texto directamente en el navegador sin descargar nada.
- **Subida de Archivos**: Sube archivos desde tu móvil al PC con barra de progreso en tiempo real.
- **Códigos QR**: Genera automáticamente códigos QR para un acceso ultra rápido.
- **Sin Bloqueos**: El servidor corre de forma asíncrona, por lo que la interfaz de control nunca se congela.

## 🚀 Instalación y Uso

1. **Clona el repositorio**:
   ```bash
   git clone https://github.com/System32GG/Portal-Archivos.git
   cd Portal-Archivos
   ```

2. **Instala las dependencias**:
   ```bash
   pip install -r requirements.txt
   ```

3. **Ejecuta la aplicación**:
   ```bash
   python compartir.py
   ```

> [!NOTE]
> Al entrar por HTTPS en red local, el navegador mostrará un aviso de seguridad. Haz clic en **"Configuración avanzada"** y **"Continuar"**. Esto ocurre porque el certificado es autofirmado localmente, pero la conexión es 100% cifrada.

## 🌐 Acceso Remoto con Ngrok

Si quieres acceder a tus archivos desde fuera de tu red WiFi (usando datos móviles, por ejemplo), la app tiene soporte integrado para **Ngrok**:

1. Crea una cuenta gratuita en [ngrok.com](https://ngrok.com/).
2. Copia tu `Authtoken` desde el dashboard de Ngrok.
3. Al abrir la app por primera vez, selecciona "Sí" cuando pregunte por Ngrok y pega tu token.
4. La app generará automáticamente un link público y un código QR para acceso remoto.

### 🏠 Dominio Estático (Opcional)
Si tienes un dominio gratuito reservado en Ngrok (ej: `tu-nombre.ngrok-free.app`), puedes pegarlo cuando la app lo solicite. Esto hará que tu enlace **nunca cambie**, incluso si reinicias el servidor.

> [!TIP]
> Si ya configuraste la app y quieres activar Ngrok o cambiar el dominio después, puedes borrar el archivo `config.json` en tu carpeta `AppData/Roaming/PortalArchivosPremium` para reiniciar la configuración.

## 🛠️ Requisitos

- Python 3.7 o superior.
- Librerías: `qrcode`, `Pillow`, `pyngrok`, `cryptography`.

## 🔒 Seguridad

Medidas de seguridad avanzadas incluidas para uso personal:
- **HTTPS Nativo**: Servidor local con soporte TLS para cifrar el tráfico WiFi.
- **Hashing PBKDF2**: Las contraseñas se protegen con 100,000 iteraciones y salt aleatorio, siguiendo estándares industriales.
- **Auto-Update**: Los usuarios con SHA-256 se actualizan automáticamente al nuevo hash al iniciar sesión.
- **Validación de rutas**: Protección contra ataques de navegación por directorios.
- **Sesiones Seguras**: Cookies protegidas con `HttpOnly` y `SameSite=Lax`.
- **Almacenamiento Local**: La configuración se almacena de forma privada en la carpeta de usuario (`AppData`).

## 📄 Licencia

Este proyecto está bajo la licencia MIT.
