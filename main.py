import os
import logging
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, filters
import yt_dlp

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

TOKEN = os.environ.get("TELEGRAM_TOKEN")

# Lista de IDs autorizados
ALLOWED_USERS = [
    5161997514,  # O seu ID
]

def is_authorized(user_id: int) -> bool:
    """Verifica se o utilizador está na lista de permissões."""
    return user_id in ALLOWED_USERS

# Servidor web simples para responder às verificações do Render (Web Service)
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/plain')
        self.end_headers()
        self.wfile.write(b"Bot is alive!")

    def log_message(self, format, *args):
        pass  # Silencia os logs do health check para não encher a consola

def run_web_server():
    # O Render atribui a porta na variável PORT, padrão 10000
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(('0.0.0.0', port), HealthCheckHandler)
    server.serve_forever()

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
        video_path = download_reel(clean_url)

        with open(video_path, 'rb') as video_file:
            await update.message.reply_video(video=video_file)

        await status_msg.delete()

    except Exception as e:
        logging.error(f"Erro: {e}")
        await status_msg.edit_text("Não foi possível transferir o vídeo. O perfil pode ser privado ou o Instagram bloqueou temporariamente.")

    finally:
        if video_path and os.path.exists(video_path):
            os.remove(video_path)

if __name__ == '__main__':
    if not TOKEN:
        raise ValueError("A variável TELEGRAM_TOKEN não foi configurada!")

    # Inicia o servidor HTTP numa thread secundária para o Render marcar o serviço como "Live"
    web_thread = threading.Thread(target=run_web_server, daemon=True)
    web_thread.start()

    # Inicia o bot do Telegram
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))

    print("Bot rodando...")
    app.run_polling()
