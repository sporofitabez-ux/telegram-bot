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
from utils.cbz import create_cbz

logging.basicConfig(level=logging.INFO)

CHAPTERS_PER_PAGE = 10
WAITING_FOR_CAP = 1
MAX_CHAPTERS_PER_REQUEST = 80

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
            f"📥 Download iniciado para {user}\nTotal: {total}"
        )

        for chapter in chapters:
            try:
                await send_chapter(message, source, chapter)
                sent += 1

                await status_msg.edit_text(
                    f"📥 {user}\nProgresso: {sent}/{total}"
                )

            except Exception as e:
                print("Erro:", e)

        await status_msg.edit_text("✅ Download finalizado.")
        current_download = None
        download_queue.task_done()


async def post_init(app):
    app.create_task(download_worker())


# ================= COMANDO YUKI =================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🌸 Yuki Manga Bot\nUse /search nome_do_manga"
    )


# ================= STATUS =================
async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = "📊 Fila:\n\n"

    if current_download:
        text += f"🔄 Em andamento: {current_download['user']}\n"
        text += f"Capítulos: {len(current_download['chapters'])}\n\n"
    else:
        text += "Nenhum download ativo.\n\n"

    text += f"📦 Na fila: {download_queue.qsize()}"

    await update.message.reply_text(text)


# ================= SEARCH =================
async def buscar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        return await update.message.reply_text("Use /search nome")

    query_text = " ".join(context.args)
    sources = get_all_sources()
    buttons = []

    for source_name, source in sources.items():
        try:
            results = await source.search(query_text)
            for manga in results[:6]:
                buttons.append([
                    InlineKeyboardButton(
                        f"{manga['title']} ({source_name})",
                        callback_data=f"m|{source_name}|{manga['url']}|0"
                    )
                ])
        except:
            pass

    await update.message.reply_text(
        f"🔎 {query_text}",
        reply_markup=InlineKeyboardMarkup(buttons)
    )


# ================= LISTAR CAPÍTULOS COM PAGINAÇÃO =================
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


# ================= OPÇÕES DOWNLOAD =================
async def chapter_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    session = get_session(context, query.message.message_id)

    _, index_str = query.data.split("|")
    session["selected_index"] = int(index_str)

    buttons = [
        [InlineKeyboardButton("📥 Baixar este", callback_data="d|single")],
        [InlineKeyboardButton("📥 Baixar deste até o fim", callback_data="d|from")],
        [InlineKeyboardButton("📥 Baixar até aqui", callback_data="d|to")],
        [InlineKeyboardButton("📥 Baixar até cap X", callback_data="input_cap")],
    ]

    await query.edit_message_text(
        "Escolha:",
        reply_markup=InlineKeyboardMarkup(buttons)
    )


# ================= PROCESSAR DOWNLOAD =================
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
    elif mode == "from":
        selected = chapters[index:]
    elif mode == "to":
        selected = chapters[: index + 1]
    else:
        return

    if len(selected) > MAX_CHAPTERS_PER_REQUEST:
        selected = selected[:MAX_CHAPTERS_PER_REQUEST]

    await download_queue.put({
        "message": query.message,
        "source": get_all_sources()[source_name],
        "chapters": selected,
        "user": query.from_user.first_name
    })

    await query.message.reply_text(
        f"📌 Adicionado à fila ({len(selected)} caps)"
    )


# ================= CAP X =================
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
        return WAITING_FOR_CAP

    reply = update.message.reply_to_message
    session = get_session(context, reply.message_id)

    chapters = session["chapters"]
    source_name = session["source_name"]

    selected = [
        c for c in chapters
        if float(c.get("chapter_number") or 0) <= cap_number
    ]

    if len(selected) > MAX_CHAPTERS_PER_REQUEST:
        selected = selected[:MAX_CHAPTERS_PER_REQUEST]

    await download_queue.put({
        "message": update.message,
        "source": get_all_sources()[source_name],
        "chapters": selected,
        "user": update.effective_user.first_name
    })

    await update.message.reply_text(
        f"📌 Adicionado à fila ({len(selected)} caps)"
    )

    return ConversationHandler.END


# ================= ENVIAR CAP =================
async def send_chapter(message, source, chapter):
    imgs = await source.pages(chapter["url"])
    if not imgs:
        return

    cbz_path, cbz_name = await create_cbz(
        imgs,
        chapter.get("manga_title", "Manga"),
        f"Cap_{chapter.get('chapter_number')}"
    )

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
