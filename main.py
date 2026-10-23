import os
import logging
import threading
import asyncio
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

# Servidor HTTP leve para o Health Check do Render e pings do UptimeRobot
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
    await update.message.reply_text("👋 Olá! Envie o link de um Reels do Instagram que eu baixo para si.")

def download_reel(url: str, output_path: str = "downloads") -> str:
    os.makedirs(output_path, exist_ok=True)
    outtmpl = os.path.join(output_path, "%(id)s.%(ext)s")
    ydl_opts = {
        'format': 'best[ext=mp4]/best',
        'outtmpl': outtmpl,
        'quiet': True,
        'no_warnings': True,
        'socket_timeout': 15,
        'retries': 3,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        return ydl.prepare_filename(info)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_authorized(user_id):
        await update.message.reply_text("⛔ Acesso negado. Apenas membros autorizados podem utilizar este serviço.")
        return

    text = update.message.text
    if "instagram.com" not in text:
        await update.message.reply_text("Por favor, envie um link válido do Instagram.")
        return

    clean_url = text.split("?")[0]
    status_msg = await update.message.reply_text("A transferir o Reels... aguarde alguns segundos.")
    video_path = None
    try:
        # Executa o download de forma não-bloqueante numa thread separada
        loop = asyncio.get_running_loop()
        video_path = await loop.run_in_executor(None, download_reel, clean_url)

        if video_path and os.path.exists(video_path):
            with open(video_path, 'rb') as video_file:
                await update.message.reply_video(video=video_file)
            await status_msg.delete()
        else:
            await status_msg.edit_text("Não foi possível localizar o ficheiro transferido.")
    except Exception as e:
        logging.error(f"Erro no download: {e}")
        await status_msg.edit_text(f"Não foi possível transferir o vídeo. Motivo: {str(e)[:120]}")
    finally:
        if video_path and os.path.exists(video_path):
            try:
                os.remove(video_path)
            except Exception:
                pass

if __name__ == '__main__':
    if not TOKEN:
        raise ValueError("A variável TELEGRAM_TOKEN não foi configurada!")

    # Inicia a thread web antes do polling
    web_thread = threading.Thread(target=run_web_server, daemon=True)
    web_thread.start()

    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))

    logging.info("Bot rodando...")
    app.run_polling()
