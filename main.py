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
from utils.queue_manager import add_job, get_position, DownloadJob, queue
from utils.worker import worker

logging.basicConfig(level=logging.INFO)

CHAPTERS_PER_PAGE = 10
WAITING_CAP = 1

# ================= SESSÕES =================
def get_sessions(context):
    if "sessions" not in context.chat_data:
        context.chat_data["sessions"] = {}
    return context.chat_data["sessions"]

def get_session(context, message_id):
    return get_sessions(context).setdefault(str(message_id), {})

def is_group(update: Update):
    return update.effective_chat.type in ["group", "supergroup"]

# ================= COMANDO /Yuki =================
async def yuki(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_group(update):
        return await update.message.reply_text("Use o bot no grupo.")
    await update.message.reply_text("🌸 Yuki online!\nUse /search nome_do_manga")

# ================= COMANDO /search =================
async def search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_group(update):
        return

    if not context.args:
        return await update.message.reply_text("Use: /search nome")

    query_text = " ".join(context.args)
    sources = get_all_sources()

    buttons = []
    for source_name, source in sources.items():
        try:
            results = await source.search(query_text)
            if not results:
                continue

            for manga in results[:6]:
                buttons.append([
                    InlineKeyboardButton(
                        f"{manga['title']} ({source_name})",
                        callback_data=f"m|{source_name}|{manga['url']}"
                    )
                ])
        except Exception as e:
            logging.warning(f"Erro na fonte {source_name}: {e}")

    if not buttons:
        return await update.message.reply_text("❌ Nenhum resultado encontrado.")

    msg = await update.message.reply_text(
        f"🔎 Resultados para: {query_text}",
        reply_markup=InlineKeyboardMarkup(buttons)
    )

    session = get_session(context, msg.message_id)
    session["owner"] = update.effective_user.id
    session["owner_name"] = update.effective_user.first_name

# ================= PROTEÇÃO DONO =================
async def check_owner(update, context):
    query = update.callback_query
    session = get_session(context, query.message.message_id)

    if query.from_user.id != session.get("owner"):
        await query.answer("❌ Este pedido pertence a outro usuário", show_alert=True)
        return None
    return session

# ================= ABRIR MANGA =================
async def manga_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    session = await check_owner(update, context)
    if not session:
        return

    _, source_name, manga_id = query.data.split("|")

    source = get_all_sources()[source_name]
    chapters = await source.chapters(manga_id)

    if not chapters:
        return await query.message.reply_text("❌ Não foi possível carregar capítulos.")

    session["chapters"] = chapters
    session["source"] = source
    session["page"] = 0

    await edit_page(query, session)

# ================= PAGINAÇÃO =================
async def edit_page(query, session):
    page = session["page"]
    chapters = session["chapters"]

    start = page * CHAPTERS_PER_PAGE
    end = start + CHAPTERS_PER_PAGE
    subset = chapters[start:end]

    buttons = []
    for i, ch in enumerate(subset, start=start):
        num = ch.get("chapter_number")
        buttons.append([InlineKeyboardButton(f"Cap {num}", callback_data=f"c|{i}")])

    nav = []
    if start > 0:
        nav.append(InlineKeyboardButton("«", callback_data="p|prev"))
    if end < len(chapters):
        nav.append(InlineKeyboardButton("»", callback_data="p|next"))
    if nav:
        buttons.append(nav)

    total_pages = (len(chapters)-1)//CHAPTERS_PER_PAGE + 1

    await query.edit_message_text(
        f"📖 Página {page+1}/{total_pages}",
        reply_markup=InlineKeyboardMarkup(buttons)
    )

async def page_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    session = await check_owner(update, context)
    if not session:
        return

    action = query.data.split("|")[1]

    if action == "next":
        session["page"] += 1
    elif action == "prev":
        session["page"] -= 1

    await edit_page(query, session)

# ================= OPÇÕES DOWNLOAD =================
async def chapter_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    session = await check_owner(update, context)
    if not session:
        return

    _, index = query.data.split("|")
    session["selected"] = int(index)

    buttons = [
        [InlineKeyboardButton("📥 Baixar este", callback_data="d|one")],
        [InlineKeyboardButton("📚 Baixar todos", callback_data="d|all")],
        [InlineKeyboardButton("🔢 Baixar até cap X", callback_data="d|until")]
    ]

    await query.edit_message_text("Escolha o tipo de download:", reply_markup=InlineKeyboardMarkup(buttons))

# ================= DOWNLOAD =================
async def download_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    session = await check_owner(update, context)
    if not session:
        return

    _, mode = query.data.split("|")
    chapters = session["chapters"]
    idx = session["selected"]

    if mode == "one":
        selected = [chapters[idx]]

    elif mode == "all":
        selected = chapters

    elif mode == "until":
        await query.message.reply_text("Digite o número do capítulo final:")
        return WAITING_CAP

    await add_to_queue(query, selected, session)

async def receive_cap(update: Update, context: ContextTypes.DEFAULT_TYPE):
    reply = update.message.reply_to_message
    if not reply:
        return ConversationHandler.END

    session = get_session(context, reply.message_id)
    if update.effective_user.id != session.get("owner"):
        return ConversationHandler.END

    try:
        end_cap = float(update.message.text)
    except:
        return ConversationHandler.END

    start_idx = session["selected"]
    chapters = session["chapters"]

    selected = [c for c in chapters[start_idx:] if float(c.get("chapter_number",0)) <= end_cap]

    await add_to_queue(update, selected, session)
    return ConversationHandler.END

# ================= FILA =================
async def add_to_queue(query_or_msg, selected, session):
    user = query_or_msg.from_user if hasattr(query_or_msg, "from_user") else query_or_msg.effective_user
    message = query_or_msg.message if hasattr(query_or_msg, "message") else query_or_msg

    job = DownloadJob(
        user_id=user.id,
        user_name=user.first_name,
        manga=selected[0].get("manga_title","Manga"),
        chapters=selected,
        message=message,
        source=session["source"]
    )

    await add_job(job)
    pos = await get_position(user.id)

    await message.reply_text(f"🕒 {user.first_name}, adicionado à fila.\nPosição: {pos}")

# ================= STATUS =================
async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not queue:
        return await update.message.reply_text("Fila vazia.")

    text = "📊 FILA\n\n"
    for i, job in enumerate(queue, start=1):
        text += f"{i}. {job.user_name} — {job.manga}\n"

    await update.message.reply_text(text)

# ================= MAIN =================
def main():
    app = ApplicationBuilder().token(os.getenv("BOT_TOKEN")).build()

    app.add_handler(CommandHandler("Yuki", yuki))
    app.add_handler(CommandHandler("search", search))
    app.add_handler(CommandHandler("status", status))

    app.add_handler(CallbackQueryHandler(manga_callback, pattern="^m\\|"))
    app.add_handler(CallbackQueryHandler(page_callback, pattern="^p\\|"))
    app.add_handler(CallbackQueryHandler(chapter_callback, pattern="^c\\|"))
    app.add_handler(CallbackQueryHandler(download_callback, pattern="^d\\|"))

    conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(download_callback, pattern="^d\\|until$")],
        states={WAITING_CAP:[MessageHandler(filters.TEXT & ~filters.COMMAND, receive_cap)]},
        fallbacks=[]
    )
    app.add_handler(conv)

    loop = asyncio.get_event_loop()
    loop.create_task(worker(app))
    loop.create_task(worker(app))

    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
