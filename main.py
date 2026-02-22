import os
import asyncio
import logging

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)

from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)

from telegram.error import RetryAfter, TimedOut, NetworkError

from utils.loader import get_all_sources
from utils.cbz import create_cbz
from utils.queue_manager import (
    DOWNLOAD_QUEUE,
    add_job,
    remove_job,
    queue_size,
)
from utils.anilist import search_anilist

logging.basicConfig(level=logging.INFO)

DOWNLOAD_SEMAPHORE = asyncio.Semaphore(2)
CHAPTERS_PER_PAGE = 10

SEARCH_CACHE = {}
BOT_MESSAGES = {}

# =====================================================
# USUÁRIOS AUTORIZADOS
# =====================================================
AUTHORIZED_USERS = [
    7506598563,  # Substitua pelo seu ID
    7943806660,  # Outro usuário autorizado
    1956546218,
]

async def is_authorized(update: Update):
    user_id = update.effective_user.id
    return user_id in AUTHORIZED_USERS


# =====================================================
# DECORADOR PARA CHECAR AUTORIZAÇÃO
# =====================================================
def authorized_only(func):
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        if not await is_authorized(update):
            await update.message.reply_text("❌ Você não tem permissão para usar este bot.")
            return
        return await func(update, context, *args, **kwargs)
    return wrapper


# =====================================================
# LIMPAR RASTROS DO BOT
# =====================================================
async def clean_bot_messages(chat_id, context):
    msgs = BOT_MESSAGES.get(chat_id, [])
    for mid in msgs:
        try:
            await context.bot.delete_message(chat_id, mid)
        except:
            pass
    BOT_MESSAGES[chat_id] = []


def register_bot_message(chat_id, message):
    BOT_MESSAGES.setdefault(chat_id, []).append(message.message_id)


# =====================================================
# ENVIO CAPÍTULO
# =====================================================
async def send_chapter(message, source, chapter):
    async with DOWNLOAD_SEMAPHORE:
        imgs = await source.pages(chapter["url"])
        if not imgs:
            return

        cbz_buffer, cbz_name = await create_cbz(
            imgs,
            chapter.get("manga_title", "Manga"),
            f"Cap_{chapter.get('chapter_number')}",
        )

        while True:
            try:
                await message.reply_document(cbz_buffer, filename=cbz_name)
                break
            except RetryAfter as e:
                await asyncio.sleep(int(e.retry_after) + 2)
            except (TimedOut, NetworkError):
                await asyncio.sleep(5)

        cbz_buffer.close()


# =====================================================
# WORKER
# =====================================================
async def worker():
    print("✅ Worker iniciado")
    while True:
        job = await DOWNLOAD_QUEUE.get()
        await send_chapter(
            job["message"],
            job["source"],
            job["chapter"],
        )
        await asyncio.sleep(2)
        remove_job()
        DOWNLOAD_QUEUE.task_done()


# =====================================================
# BUSCAR (AGORA /BB)
# =====================================================
@authorized_only
async def buscar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    await clean_bot_messages(chat_id, context)

    query = " ".join(context.args)
    if not query:
        await update.message.reply_text("❌ Use /bb <nome do mangá>")
        return

    msg = await update.message.reply_text("🔎 Buscando...")
    register_bot_message(chat_id, msg)

    buttons = []
    cache = []

    for source_name, source in get_all_sources().items():
        try:
            results = await source.search(query)
            for manga in results[:5]:
                cache.append({
                    "source": source_name,
                    "title": manga["title"],
                    "url": manga["url"],
                })
                buttons.append([
                    InlineKeyboardButton(
                        f"{manga['title']} ({source_name})",
                        callback_data=f"select|{len(cache)-1}",
                    )
                ])
        except:
            pass

    if not buttons:
        await msg.edit_text("❌ Nenhum resultado encontrado.")
        return

    SEARCH_CACHE[chat_id] = cache
    await msg.edit_text(
        "📚 Escolha o mangá:",
        reply_markup=InlineKeyboardMarkup(buttons),
    )


# =====================================================
# SELECIONAR MANGÁ
# =====================================================
@authorized_only
async def select_manga(update, context):
    query = update.callback_query
    await query.answer()

    chat_id = query.message.chat_id
    data = SEARCH_CACHE[chat_id][int(query.data.split("|")[1])]
    source = get_all_sources()[data["source"]]

    info = await search_anilist(data["title"])
    chapters = await source.chapters(data["url"])

    context.chat_data["chapters"] = chapters
    context.chat_data["source"] = source

    text = (
        f"📖 *{info['title']}*\n\n"
        f"🎭 {info['genres']}\n\n"
        f"{info['synopsis']}"
    )

    buttons = [
        [InlineKeyboardButton("📥 Baixar tudo", callback_data="download_all")],
        [InlineKeyboardButton("📖 Ver capítulos", callback_data="chapters|0")],
    ]

    await query.message.reply_photo(
        info["cover"],
        caption=text,
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(buttons),
    )


# =====================================================
# PAGINAÇÃO CAPÍTULOS
# =====================================================
@authorized_only
async def show_chapters(update, context):
    query = update.callback_query
    await query.answer()

    page = int(query.data.split("|")[1])
    chapters = context.chat_data["chapters"]

    start = page * CHAPTERS_PER_PAGE
    end = start + CHAPTERS_PER_PAGE
    subset = chapters[start:end]

    buttons = [
        [
            InlineKeyboardButton(
                f"Cap {c.get('chapter_number')}",
                callback_data=f"download_one|{start+i}",
            )
        ]
        for i, c in enumerate(subset)
    ]

    nav = []
    if start > 0:
        nav.append(InlineKeyboardButton("◀", callback_data=f"chapters|{page-1}"))
    if end < len(chapters):
        nav.append(InlineKeyboardButton("▶", callback_data=f"chapters|{page+1}"))

    if nav:
        buttons.append(nav)

    await query.message.edit_text(
        "📖 Escolha capítulo:",
        reply_markup=InlineKeyboardMarkup(buttons),
    )


# =====================================================
# DOWNLOADS
# =====================================================
@authorized_only
async def download_all(update, context):
    query = update.callback_query
    await query.answer()

    chapters = context.chat_data["chapters"]
    source = context.chat_data["source"]

    for ch in chapters:
        await add_job({
            "message": query.message,
            "source": source,
            "chapter": ch,
            "meta": {},
        })

    await query.message.reply_text("✅ Todos capítulos adicionados à fila.")


@authorized_only
async def download_one(update, context):
    query = update.callback_query
    await query.answer()

    index = int(query.data.split("|")[1])
    ch = context.chat_data["chapters"][index]
    source = context.chat_data["source"]

    await add_job({
        "message": query.message,
        "source": source,
        "chapter": ch,
        "meta": {},
    })

    await query.message.reply_text("✅ Capítulo adicionado à fila.")


# =====================================================
# STATUS
# =====================================================
@authorized_only
async def status(update, context):
    await update.message.reply_text(f"📦 Fila: {queue_size()}")


# =====================================================
# MAIN
# =====================================================
def main():
    app = ApplicationBuilder().token(os.getenv("BOT_TOKEN")).build()

    # Comandos
    app.add_handler(CommandHandler("bb", buscar))
    app.add_handler(CommandHandler("status", status))

    # Callbacks
    app.add_handler(CallbackQueryHandler(select_manga, pattern="^select"))
    app.add_handler(CallbackQueryHandler(show_chapters, pattern="^chapters"))
    app.add_handler(CallbackQueryHandler(download_all, pattern="download_all"))
    app.add_handler(CallbackQueryHandler(download_one, pattern="download_one"))

    async def startup(app):
        asyncio.create_task(worker())

    app.post_init = startup

    print("🤖 Biblioteca308 bot")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
