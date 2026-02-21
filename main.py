import os
import logging
import asyncio

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)

from utils.loader import get_all_sources
from utils.cbz import create_cbz

logging.basicConfig(level=logging.INFO)

CHAPTERS_PER_PAGE = 10
MAX_CHAPTERS_PER_REQUEST = 50

# ================= FILA GLOBAL =================
download_queue = asyncio.Queue()
current_download = None


# ================= SESSÕES =================
def get_sessions(context):
    if "sessions" not in context.chat_data:
        context.chat_data["sessions"] = {}
    return context.chat_data["sessions"]


def get_session(context, message_id):
    return get_sessions(context).setdefault(str(message_id), {})


def block_private(update: Update):
    return update.effective_chat.type == "private"


# ================= WORKER =================
async def download_worker():
    global current_download

    while True:
        job = await download_queue.get()
        current_download = job

        message = job["message"]
        source = job["source"]
        chapters = job["chapters"]
        user = job["user"]

        total = len(chapters)
        sent = 0

        status_msg = await message.reply_text(
            f"📥 Download iniciado para {user}\n"
            f"Total: {total} capítulos"
        )

        for chapter in chapters:
            try:
                await send_chapter(message, source, chapter)
                sent += 1

                await status_msg.edit_text(
                    f"📥 Baixando para {user}\n"
                    f"Progresso: {sent}/{total}"
                )

            except Exception as e:
                print(f"Erro no capítulo: {e}")

        await status_msg.edit_text("✅ Download finalizado.")
        current_download = None
        download_queue.task_done()


# ================= POST INIT =================
async def post_init(application):
    application.create_task(download_worker())


# ================= COMANDO YUKI =================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if block_private(update):
        return await update.effective_message.reply_text(
            "❌ Bot disponível apenas no grupo."
        )

    await update.effective_message.reply_text(
        "🌸 Yuki Manga Bot Online!\n\nUse:\n/search nome_do_manga"
    )


# ================= STATUS =================
async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = "📊 Status da Fila\n\n"

    if current_download:
        text += f"🔄 Em andamento: {current_download['user']}\n"
        text += f"Capítulos: {len(current_download['chapters'])}\n\n"
    else:
        text += "🔄 Nenhum download em andamento\n\n"

    text += f"📦 Na fila: {download_queue.qsize()}"

    await update.message.reply_text(text)


# ================= SEARCH =================
async def buscar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if block_private(update):
        return

    if not context.args:
        return await update.effective_message.reply_text(
            "Use:\n/search nome_do_manga"
        )

    query_text = " ".join(context.args)
    sources = get_all_sources()
    buttons = []

    for source_name, source in sources.items():
        try:
            results = await source.search(query_text)
            for manga in results[:6]:
                title = manga.get("title")
                url = manga.get("url")

                buttons.append([
                    InlineKeyboardButton(
                        f"{title} ({source_name})",
                        callback_data=f"m|{source_name}|{url}|0"
                    )
                ])
        except Exception:
            continue

    if not buttons:
        return await update.effective_message.reply_text(
            "❌ Nenhum resultado encontrado."
        )

    msg = await update.effective_message.reply_text(
        f"🔎 Resultados para: {query_text}",
        reply_markup=InlineKeyboardMarkup(buttons),
    )

    session = get_session(context, msg.message_id)
    session["owner_id"] = update.effective_user.id


# ================= LISTAR CAPÍTULOS =================
async def manga_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    _, source_name, manga_id, page_str = query.data.split("|")
    page = int(page_str)

    source = get_all_sources()[source_name]
    chapters = await source.chapters(manga_id)

    session = get_session(context, query.message.message_id)
    session["chapters"] = chapters
    session["source_name"] = source_name

    total = len(chapters)
    start = page * CHAPTERS_PER_PAGE
    end = start + CHAPTERS_PER_PAGE
    subset = chapters[start:end]

    buttons = []
    for i, ch in enumerate(subset, start=start):
        num = ch.get("chapter_number") or ch.get("name")

        buttons.append([
            InlineKeyboardButton(
                f"Cap {num}",
                callback_data=f"c|{i}"
            )
        ])

    await query.edit_message_text(
        "📖 Selecione o capítulo:",
        reply_markup=InlineKeyboardMarkup(buttons)
    )


# ================= DOWNLOAD =================
async def chapter_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    session = get_session(context, query.message.message_id)

    _, index_str = query.data.split("|")
    index = int(index_str)

    chapters = session["chapters"]
    source_name = session["source_name"]

    selected = chapters[index:]

    if len(selected) > MAX_CHAPTERS_PER_REQUEST:
        selected = selected[:MAX_CHAPTERS_PER_REQUEST]

    await download_queue.put({
        "message": query.message,
        "source": get_all_sources()[source_name],
        "chapters": selected,
        "user": query.from_user.first_name
    })

    await query.message.reply_text(
        f"📌 Adicionado à fila.\n"
        f"Capítulos: {len(selected)}"
    )


# ================= ENVIAR CAPÍTULO =================
async def send_chapter(message, source, chapter):
    cid = chapter.get("url")
    num = chapter.get("chapter_number")
    manga_title = chapter.get("manga_title", "Manga")

    imgs = await source.pages(cid)
    if not imgs:
        return

    cbz_path, cbz_name = await create_cbz(imgs, manga_title, f"Cap_{num}")

    await message.reply_document(
        document=open(cbz_path, "rb"),
        filename=cbz_name
    )

    os.remove(cbz_path)


# ================= MAIN =================
def main():
    app = (
        ApplicationBuilder()
        .token(os.getenv("BOT_TOKEN"))
        .post_init(post_init)
        .build()
    )

    app.add_handler(CommandHandler("Yuki", start))
    app.add_handler(CommandHandler("search", buscar))
    app.add_handler(CommandHandler("status", status))

    app.add_handler(CallbackQueryHandler(manga_callback, pattern="^m\\|"))
    app.add_handler(CallbackQueryHandler(chapter_callback, pattern="^c\\|"))

    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
