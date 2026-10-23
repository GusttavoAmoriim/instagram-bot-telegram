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

def get_video_duration(file_path: str) -> float:
    try:
        cmd = [
            "ffprobe", "-v", "error", "-show_entries",
            "format=duration", "-of", "default=noprint_wrappers=1:nokey=1",
            file_path
        ]
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)
        return float(result.stdout.strip())
    except Exception as e:
        logging.warning(f"Não foi possível obter duração: {e}")
        return 60.0

def compress_video(input_path: str, target_size_mb: float = 38.0) -> str:
    duration = get_video_duration(input_path)
    if duration <= 0:
        duration = 60.0

    target_total_bitrate = (target_size_mb * 8 * 1024 * 1024) / duration
    audio_bitrate = 96 * 1024
    video_bitrate = target_total_bitrate - audio_bitrate

    if video_bitrate < 150 * 1024:
        video_bitrate = 150 * 1024

    output_path = f"{os.path.splitext(input_path)[0]}_compressed.mp4"

    cmd = [
        "ffmpeg", "-y", "-i", input_path,
        "-b:v", f"{int(video_bitrate)}",
        "-maxrate", f"{int(video_bitrate * 1.3)}",
        "-bufsize", f"{int(video_bitrate * 2)}",
        "-preset", "veryfast",
        "-c:v", "libx264",
        "-c:a", "aac",
        "-b:a", "96k",
        output_path
    ]

    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
    return output_path

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_authorized(user_id):
        await update.message.reply_text("⛔ Acesso negado. Apenas usuários autorizados podem utilizar este serviço.")
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
            timeout=70.0
        )

        if video_path and os.path.exists(video_path):
            file_size_mb = os.path.getsize(video_path) / (1024 * 1024)
            final_upload_path = video_path

            if file_size_mb > 49.0:
                await status_msg.edit_text(f"O vídeo tem {file_size_mb:.1f} MB. A comprimir para respeitar o limite de 50 MB...")
                compressed_path = await loop.run_in_executor(None, compress_video, video_path)
                final_upload_path = compressed_path

            await status_msg.edit_text("A enviar vídeo para o Telegram...")
            with open(final_upload_path, 'rb') as video_file:
                await update.message.reply_video(
                    video=video_file,
                    write_timeout=180,
                    read_timeout=180,
                    connect_timeout=60
                )
            await status_msg.delete()
        else:
            await status_msg.edit_text("⚠️ Não foi possível localizar o ficheiro transferido.")
            
    except asyncio.TimeoutError:
        await status_msg.edit_text("⏱️ O processo demorou muito tempo. A requisição expirou.")
    except Exception as e:
        logging.error(f"Erro no processamento: {e}")
        await status_msg.edit_text(f"❌ Não foi possível enviar o vídeo: {str(e)[:120]}")
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
