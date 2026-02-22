import os
import logging
import asyncio

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from utils.loader import get_all_sources
from core.job_manager import MangaJob
from core.queue_manager import download_queue, current_job, worker

logging.basicConfig(level=logging.INFO)

CHAPTERS_PER_PAGE = 10
WAITING_FOR_CAP = 1
MAX_CHAPTERS_PER_REQUEST = 300


# ================= UTILS =================
def sort_chapters(chapters):
    def get_number(ch):
        try:
            return float(ch.get("chapter_number") or 0)
        except:
            return 0
    return sorted(chapters, key=get_number)


def get_sessions(context):
    if "sessions" not in context.chat_data:
        context.chat_data["sessions"] = {}
    return context.chat_data["sessions"]


def get_session(context, message_id):
    return get_sessions(context).setdefault(str(message_id), {})


# ================= WORKER INIT =================
async def post_init(app):
    app.create_task(worker())


# ================= START =================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🌸 Yuki Manga Bot\n\nUse /search nome_do_manga"
    )


# ================= STATUS =================
async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = "📊 Status\n\n"

    if current_job:
        text += (
            f"🔄 Em andamento\n"
            f"Usuário: {current_job.user_id}\n"
            f"Progresso: {current_job.progress}/{current_job.total}\n\n"
        )
    else:
        text += "Nenhum job ativo\n\n"

    text += f"📦 Na fila: {download_queue.qsize()}"

    await update.message.reply_text(text)


# ================= SEARCH =================
async def buscar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        return await update.message.reply_text("Use /search nome")

    query_text = " ".join(context.args)
    sources = get_all_sources()
    buttons = []

    msg = await update.message.reply_text("🔎 Buscando...")

    for source_name, source in sources.items():
        try:
            results = await asyncio.wait_for(
                source.search(query_text),
                timeout=20
            )

            for manga in results[:6]:
                buttons.append([
                    InlineKeyboardButton(
                        f"{manga['title']} ({source_name})",
                        callback_data=f"m|{source_name}|{manga['url']}|0"
                    )
                ])
        except:
            continue

    if not buttons:
        return await msg.edit_text("❌ Nenhum resultado.")

    await msg.edit_text(
        f"🔎 Resultados para: {query_text}",
        reply_markup=InlineKeyboardMarkup(buttons)
    )


# ================= CAPÍTULOS =================
async def manga_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    _, source_name, manga_id, page_str = query.data.split("|")
    page = int(page_str)

    source = get_all_sources()[source_name]
    chapters = sort_chapters(await source.chapters(manga_id))

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

    nav = []
    if start > 0:
        nav.append(
            InlineKeyboardButton("«", callback_data=f"m|{source_name}|{manga_id}|{page-1}")
        )
    if end < total:
        nav.append(
            InlineKeyboardButton("»", callback_data=f"m|{source_name}|{manga_id}|{page+1}")
        )

    if nav:
        buttons.append(nav)

    await query.edit_message_text(
        "📖 Selecione:",
        reply_markup=InlineKeyboardMarkup(buttons)
    )


# ================= OPÇÕES =================
async def chapter_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    session = get_session(context, query.message.message_id)
    _, index_str = query.data.split("|")

    session["selected_index"] = int(index_str)

    buttons = [
        [InlineKeyboardButton("📥 Baixar este", callback_data="d|single")],
        [InlineKeyboardButton("📥 Baixar todos", callback_data="d|all")],
        [InlineKeyboardButton("📥 Baixar até cap X", callback_data="input_cap")],
    ]

    await query.edit_message_text(
        "Escolha:",
        reply_markup=InlineKeyboardMarkup(buttons)
    )


# ================= DOWNLOAD =================
async def download_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    session = get_session(context, query.message.message_id)
    chapters = session["chapters"]
    index = session["selected_index"]
    source_name = session["source_name"]

    _, mode = query.data.split("|")

    if mode == "single":
        selected = [chapters[index]]
    elif mode == "all":
        selected = chapters
    else:
        return

    selected = selected[:MAX_CHAPTERS_PER_REQUEST]

    job = MangaJob(
        user_id=query.from_user.id,
        message=query.message,
        source=get_all_sources()[source_name],
        chapters=selected
    )

    await download_queue.put(job)

    await query.message.reply_text(
        f"📌 Adicionado à fila.\nCapítulos: {job.total}"
    )


# ================= ATÉ CAP X =================
async def input_cap_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    await update.callback_query.message.reply_text(
        "Digite o número do capítulo:"
    )
    return WAITING_FOR_CAP


async def receive_cap_number(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        cap_number = float(update.message.text.strip())
    except:
        await update.message.reply_text("Número inválido.")
        return WAITING_FOR_CAP

    reply = update.message.reply_to_message
    if not reply:
        return ConversationHandler.END

    session = get_session(context, reply.message_id)
    chapters = session["chapters"]
    source_name = session["source_name"]

    selected = []

    for c in chapters:
        try:
            num = float(c.get("chapter_number") or 0)
            if num <= cap_number:
                selected.append(c)
        except:
            continue

    if not selected:
        await update.message.reply_text("Nenhum capítulo encontrado.")
        return ConversationHandler.END

    job = MangaJob(
        user_id=update.effective_user.id,
        message=update.message,
        source=get_all_sources()[source_name],
        chapters=selected
    )

    await download_queue.put(job)

    await update.message.reply_text(
        f"📌 Adicionado à fila.\nCapítulos: {job.total}"
    )

    return ConversationHandler.END


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
    app.add_handler(CallbackQueryHandler(download_callback, pattern="^d\\|"))

    conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(input_cap_callback, pattern="^input_cap$")],
        states={
            WAITING_FOR_CAP: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_cap_number)
            ]
        },
        fallbacks=[]
    )

    app.add_handler(conv)

    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
