import asyncio
import os
import logging
from collections import deque

from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackQueryHandler,
    ContextTypes, MessageHandler, filters, ConversationHandler
)

from utils.loader import get_all_sources
from utils.cbz import create_cbz
import utils.downloader as dl

logging.basicConfig(level=logging.INFO)

MAX_SIMULTANEOUS_DOWNLOADS = 2
STATUS_PER_PAGE = 10

WAITING_CAP_NUMBER = 1
WAITING_ORDER = 2

download_queue = deque()
running_tasks = set()
semaphore = asyncio.Semaphore(MAX_SIMULTANEOUS_DOWNLOADS)


# ===== AUTO DETECT DOWNLOAD FUNCTION =====
async def download_wrapper(manga, cap):
    for name in ("download_chapter", "download_cap", "download", "get_chapter"):
        fn = getattr(dl, name, None)
        if fn:
            return await fn(manga, cap)
    raise Exception("Nenhuma função de download encontrada no downloader.py")


# ===== GROUP ONLY =====
def group_only(func):
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.effective_chat.type not in ["group", "supergroup"]:
            return
        return await func(update, context)
    return wrapper


def uname(user):
    return user.first_name


# ================= START =================
@group_only
async def yuki(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Yuki pronta 🌸\nUse /search nome_do_manga")


# ================= SEARCH =================
@group_only
async def search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = " ".join(context.args)
    if not query:
        return await update.message.reply_text("Digite o nome do mangá.")

    results = await get_all_sources(query)
    if not results:
        return await update.message.reply_text("Nenhum resultado.")

    context.user_data["results"] = results

    kb = []
    for i, r in enumerate(results):
        kb.append([InlineKeyboardButton(r["title"], callback_data=f"sel|{update.effective_user.id}|{i}")])

    await update.message.reply_text("Resultados:", reply_markup=InlineKeyboardMarkup(kb))


# ================= SELECT =================
@group_only
async def select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    _, uid, idx = q.data.split("|")
    if int(uid) != q.from_user.id:
        return

    manga = context.user_data["results"][int(idx)]
    context.user_data["manga"] = manga
    context.user_data["page"] = 0

    await show_chapters(q, context)


# ================= CHAPTER LIST =================
async def show_chapters(q, context):
    manga = context.user_data["manga"]
    page = context.user_data["page"]

    per = 10
    chs = manga["chapters"][page*per:(page+1)*per]

    kb = []
    for c in chs:
        kb.append([InlineKeyboardButton(f"Cap {c['number']}", callback_data=f"cap|{q.from_user.id}|{c['number']}")])

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("«", callback_data="prev"))
    if (page+1)*per < len(manga["chapters"]):
        nav.append(InlineKeyboardButton("»", callback_data="next"))
    if nav:
        kb.append(nav)

    await q.edit_message_text(manga["title"], reply_markup=InlineKeyboardMarkup(kb))


async def nav(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    if q.data == "next":
        context.user_data["page"] += 1
    else:
        context.user_data["page"] -= 1

    await show_chapters(q, context)


# ================= OPTIONS =================
async def chapter(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    _, uid, cap = q.data.split("|")
    if int(uid) != q.from_user.id:
        return

    context.user_data["selected"] = int(cap)

    kb = [
        [InlineKeyboardButton("Baixar este", callback_data="one")],
        [InlineKeyboardButton("Baixar todos", callback_data="all")],
        [InlineKeyboardButton("Baixar até X", callback_data="until")]
    ]

    await q.edit_message_text(f"Capítulo {cap}", reply_markup=InlineKeyboardMarkup(kb))


# ================= ORDER =================
async def ask_order(q, context, mode):
    context.user_data["mode"] = mode
    await q.edit_message_text("Ordem?",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("Crescente", callback_data="ord_c")],
            [InlineKeyboardButton("Decrescente", callback_data="ord_d")]
        ])
    )


async def one(update, context):
    q = update.callback_query
    await q.answer()
    await ask_order(q, context, "one")


async def all_caps(update, context):
    q = update.callback_query
    await q.answer()
    await ask_order(q, context, "all")


async def until(update, context):
    q = update.callback_query
    await q.answer()
    await q.message.reply_text("Digite o capítulo final:")
    return WAITING_CAP_NUMBER


async def receive_cap(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["until"] = int(update.message.text)
    await update.message.reply_text("Escolha ordem:",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("Crescente", callback_data="ord_c")],
            [InlineKeyboardButton("Decrescente", callback_data="ord_d")]
        ])
    )
    context.user_data["mode"] = "range"
    return WAITING_ORDER


async def order(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    order = "asc" if q.data == "ord_c" else "desc"
    await enqueue(q.from_user, q.message.chat_id, context, order)
    return ConversationHandler.END


# ================= QUEUE =================
async def enqueue(user, chat_id, context, order):
    manga = context.user_data["manga"]
    start = context.user_data["selected"]
    mode = context.user_data["mode"]

    if mode == "one":
        caps = [start]
    elif mode == "all":
        caps = [c["number"] for c in manga["chapters"]]
    else:
        end = context.user_data["until"]
        caps = list(range(start, end+1))

    if order == "desc":
        caps.reverse()

    download_queue.append({
        "user": user,
        "chat": chat_id,
        "manga": manga,
        "caps": caps
    })

    await context.bot.send_message(chat_id, f"{uname(user)} seu download foi adicionado à fila.")

    asyncio.create_task(process_queue(context.bot))


# ================= PROCESS =================
async def process_queue(bot):
    if len(running_tasks) >= MAX_SIMULTANEOUS_DOWNLOADS:
        return
    if not download_queue:
        return

    req = download_queue.popleft()
    task = asyncio.create_task(run_download(bot, req))
    running_tasks.add(task)
    task.add_done_callback(lambda t: running_tasks.remove(t) or asyncio.create_task(process_queue(bot)))


async def run_download(bot, req):
    user = req["user"]
    manga = req["manga"]
    chat = req["chat"]

    await bot.send_message(chat, f"{uname(user)} - {manga['title']} download iniciado")

    for cap in req["caps"]:
        path = await download_wrapper(manga, cap)
        cbz = await create_cbz(path)

        await bot.send_document(chat, cbz)

        try:
            os.remove(cbz)
        except:
            pass

    await bot.send_message(chat, f"{uname(user)} - {manga['title']} download concluído")


# ================= STATUS =================
@group_only
async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not download_queue:
        return await update.message.reply_text("Fila vazia.")

    page = int(context.args[0]) if context.args else 1
    start = (page-1)*STATUS_PER_PAGE
    end = start+STATUS_PER_PAGE

    txt = f"Fila página {page}\n"
    for i, r in enumerate(list(download_queue)[start:end], start=start+1):
        txt += f"{i}. {r['user'].first_name} - {r['manga']['title']}\n"

    await update.message.reply_text(txt)


# ================= MAIN =================
def main():
    app = ApplicationBuilder().token("TOKEN_AQUI").build()

    conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(until, pattern="until")],
        states={
            WAITING_CAP_NUMBER: [MessageHandler(filters.TEXT, receive_cap)],
            WAITING_ORDER: [CallbackQueryHandler(order)]
        },
        fallbacks=[]
    )

    app.add_handler(CommandHandler("Yuki", yuki))
    app.add_handler(CommandHandler("search", search))
    app.add_handler(CommandHandler("status", status))

    app.add_handler(CallbackQueryHandler(select, pattern="sel"))
    app.add_handler(CallbackQueryHandler(nav, pattern="prev|next"))
    app.add_handler(CallbackQueryHandler(chapter, pattern="cap"))

    app.add_handler(CallbackQueryHandler(one, pattern="one"))
    app.add_handler(CallbackQueryHandler(all_caps, pattern="all"))

    app.add_handler(conv)

    app.run_polling()


if __name__ == "__main__":
    main()
