import os
import re
import logging
import threading
import asyncio
import subprocess
from http.server import HTTPServer, BaseHTTPRequestHandler
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, filters
import yt_dlp

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

TOKEN = os.environ.get("TELEGRAM_TOKEN")

ALLOWED_USERS = [
    5161997514,
]

def is_authorized(user_id: int) -> bool:
    return user_id in ALLOWED_USERS

# Servidor HTTP para Health Check do Render e pings do UptimeRobot
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/plain; charset=utf-8')
        self.end_headers()
        self.wfile.write(b"Bot is alive!")

    def do_HEAD(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/plain; charset=utf-8')
        self.end_headers()

    def log_message(self, format, *args):
        pass

def run_web_server():
    port_str = os.environ.get("PORT", "10000")
    port = int(port_str)
    server_address = ('0.0.0.0', port)
    httpd = HTTPServer(server_address, HealthCheckHandler)
    logging.info(f"Servidor web ativo na porta {port}")
    httpd.serve_forever()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_authorized(user_id):
        await update.message.reply_text("⛔ Acesso não autorizado. Este bot é de uso estritamente privado.")
        return
    await update.message.reply_text("👋 Olá! Envie o link de um Reels do Instagram que eu descarrego para você.")

def download_reel(url: str, output_path: str = "downloads") -> str:
    os.makedirs(output_path, exist_ok=True)
    outtmpl = os.path.join(output_path, "%(id)s.%(ext)s")
    
    ydl_opts = {
        'format': 'best[ext=mp4]/best',
        'outtmpl': outtmpl,
        'quiet': True,
        'no_warnings': True,
        'socket_timeout': 15,
        'retries': 2,
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
            'Accept-Language': 'en-US,en;q=0.9',
        }
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        return ydl.prepare_filename(info)

def compress_video(input_path: str) -> str:
    output_path = f"{os.path.splitext(input_path)[0]}_compressed.mp4"

    # Redimensiona mantendo proporção para largura máxima de 720px e comprime via CRF 28 (baixo consumo de RAM e alta redução de tamanho)
    cmd = [
        "ffmpeg", "-y", "-i", input_path,
        "-vf", "scale=720:-2:flags=lanczos",
        "-c:v", "libx264",
        "-crf", "28",
        "-preset", "ultrafast",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        "-b:a", "128k",
        output_path
    ]

    process = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=180
    )

    if process.returncode != 0:
        err_msg = process.stderr.strip().splitlines()[-1] if process.stderr else "Erro desconhecido no ffmpeg"
        logging.error(f"Erro completo ffmpeg: {process.stderr}")
        raise RuntimeError(f"FFmpeg falhou: {err_msg}")

    return output_path

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_authorized(user_id):
        await update.message.reply_text("⛔ Acesso negado. Apenas utilizadores autorizados podem utilizar este serviço.")
        return

    text = update.message.text or ""
    
    match = re.search(r'(https?://(?:www\.)?instagram\.com/[^\s]+)', text)
    if not match:
        await update.message.reply_text("Por favor, envie um link válido do Instagram.")
        return

    clean_url = match.group(1).split("?")[0]
    status_msg = await update.message.reply_text("A transferir o Reels... aguarde alguns segundos.")
    video_path = None
    compressed_path = None
    
    try:
        loop = asyncio.get_running_loop()
        video_path = await asyncio.wait_for(
            loop.run_in_executor(None, download_reel, clean_url),
            timeout=80.0
        )

        if video_path and os.path.exists(video_path):
            file_size_mb = os.path.getsize(video_path) / (1024 * 1024)
            final_upload_path = video_path

            if file_size_mb > 49.0:
                await status_msg.edit_text(f"O vídeo tem {file_size_mb:.1f} MB. A comprimir para o limite do Telegram...")
                compressed_path = await loop.run_in_executor(None, compress_video, video_path)
                final_upload_path = compressed_path

            await status_msg.edit_text("A enviar vídeo para o Telegram...")
            with open(final_upload_path, 'rb') as video_file:
                await update.message.reply_video(
                    video=video_file,
                    write_timeout=240,
                    read_timeout=240,
                    connect_timeout=60
                )
            await status_msg.delete()
        else:
            await status_msg.edit_text("⚠️ Não foi possível localizar o ficheiro transferido.")
            
    except asyncio.TimeoutError:
        await status_msg.edit_text("⏱️ O processo demorou demasiado tempo (tempo limite excedido).")
    except Exception as e:
        logging.error(f"Erro no processamento: {e}")
        await status_msg.edit_text(f"❌ {str(e)[:150]}")
    finally:
        for path in [video_path, compressed_path]:
            if path and os.path.exists(path):
                try:
                    os.remove(path)
                except Exception:
                    pass

if __name__ == '__main__':
    if not TOKEN:
        raise ValueError("A variável TELEGRAM_TOKEN não foi configurada!")

    web_thread = threading.Thread(target=run_web_server, daemon=True)
    web_thread.start()

    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))

    logging.info("Bot rodando...")
    app.run_polling()
