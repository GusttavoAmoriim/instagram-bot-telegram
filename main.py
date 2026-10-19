import os
import logging
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, filters
import yt_dlp

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# Pega o token direto das variáveis de ambiente do Render por segurança
TOKEN = os.environ.get("TELEGRAM_TOKEN")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👋 Olá! Envie o link de um Reels do Instagram que eu baixo para você.")

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
    text = update.message.text

    if "instagram.com" not in text:
        await update.message.reply_text("Por favor, envie um link válido do Instagram.")
        return

    # Limpa parâmetros de rastreamento do link se houver
    clean_url = text.split("?")[0]
    status_msg = await update.message.reply_text("Baixando o Reels... aguarde alguns segundos.")

    video_path = None
    try:
        video_path = download_reel(clean_url)

        with open(video_path, 'rb') as video_file:
            await update.message.reply_video(video=video_file)

        await status_msg.delete()

    except Exception as e:
        logging.error(f"Erro: {e}")
        await status_msg.edit_text("Não foi possível baixar o vídeo. O perfil pode ser privado ou o Instagram bloqueou a requisição temporariamente.")

    finally:
        if video_path and os.path.exists(video_path):
            os.remove(video_path)

if __name__ == '__main__':
    if not TOKEN:
        raise ValueError("A variável TELEGRAM_TOKEN não foi configurada!")

    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))

    print("Bot rodando...")
    app.run_polling()
