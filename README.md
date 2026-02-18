# 🗂️ Portal de Archivos Universal

Una herramienta potente y sencilla en Python para compartir archivos entre tu PC y otros dispositivos (Móviles, Tablets, otras PCs) a través de WiFi o Internet (vía Ngrok).

![Python Version](https://img.shields.io/badge/python-3.7%2B-blue)
![License](https://img.shields.io/badge/license-MIT-green)

## ✨ Características

- **Acceso Local & Remoto**: Comparte por WiFi local o usa el túnel de **Ngrok** para acceder desde cualquier lugar con datos móviles.
- **Interfaz Moderna**: Diseño limpio y premium con **Modo Oscuro** automático.
- **Explorador Full**: Navega por tus discos locales, descarga carpetas completas como **ZIP**.
- **Seguridad**: Acceso protegido por contraseña (hasheada con SHA-256).
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

## 🛠️ Requisitos

- Python 3.7 o superior.
- Librerías: `qrcode`, `Pillow`, `pyngrok`.

## 🔒 Seguridad

Medidas de seguridad básicas incluidas para uso personal:
- Acceso protegido por contraseña con hasheo SHA-256.
- Validación simple de rutas para limitar el acceso a las unidades del sistema.
- Manejo de sesiones mediante cookies (atributos `HttpOnly` y `SameSite=Lax`).
- La configuración se almacena localmente en la carpeta de usuario (`AppData`).

## 📄 Licencia

Este proyecto está bajo la licencia MIT.



