import os
import logging
import traceback
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)

from sources.toonbr import ToonBr
from sources.mangaflix import MangaFlix
from utils.cbz import create_cbz

logging.basicConfig(level=logging.INFO)

# ================= FONTES =================
SOURCES = {
    "ToonBr": ToonBr(),
    "MangaFlix": MangaFlix(),
}

CHAPTERS_PER_PAGE = 10


# ================= ERROR HANDLER =================
async def error_handler(update, context):
    print("========== ERRO GLOBAL ==========")
    traceback.print_exception(None, context.error, context.error.traceback)
    print("==================================")


# ================= START =================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📚 Olá! Sou Yuki um Bot de download de mangas Online!\n\nUse:\n/buscar nome_do_manga"
    )


# ================= BUSCAR =================
async def buscar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        return await update.message.reply_text("Use: /buscar nome")

    query_text = " ".join(context.args)

    buttons = []

    for source_name, source in SOURCES.items():
        try:
            results = await source.search(query_text)

            for manga in results[:5]:
                buttons.append([
                    InlineKeyboardButton(
                        f"[{source_name}] {manga['title']}",
                        callback_data=f"m|{source_name}|{manga['url']}|0"
                    )
                ])
        except Exception as e:
            print(f"Erro na fonte {source_name}: {e}")

    if not buttons:
        return await update.message.reply_text("Nenhum resultado encontrado.")

    await update.message.reply_text(
        f"🔎 Resultados para: {query_text}",
        reply_markup=InlineKeyboardMarkup(buttons)
    )


# ================= LISTA CAPÍTULOS =================
async def manga_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    _, source_name, slug, page_str = query.data.split("|")
    page = int(page_str)

    source = SOURCES.get(source_name)
    if not source:
        return await query.message.reply_text("Fonte inválida.")

    chapters = await source.chapters(slug)

    context.user_data["chapters"] = chapters
    context.user_data["slug"] = slug
    context.user_data["source_name"] = source_name

    total = len(chapters)
    start = page * CHAPTERS_PER_PAGE
    end = start + CHAPTERS_PER_PAGE
    subset = chapters[start:end]

    buttons = []

    for i, ch in enumerate(subset, start=start):
        chap_num = ch.get("chapter_number") or "?"
        buttons.append([
            InlineKeyboardButton(
                f"Cap {chap_num}",
                callback_data=f"c|{i}"
            )
        ])

    nav = []
    if start > 0:
        nav.append(
            InlineKeyboardButton("«", callback_data=f"m|{source_name}|{slug}|{page-1}")
        )
    if end < total:
        nav.append(
            InlineKeyboardButton("»", callback_data=f"m|{source_name}|{slug}|{page+1}")
        )
    if nav:
        buttons.append(nav)

    await query.edit_message_text(
        "📖 Selecione o capítulo:",
        reply_markup=InlineKeyboardMarkup(buttons)
    )


# ================= OPÇÕES DE DOWNLOAD =================
async def chapter_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    _, index_str = query.data.split("|")
    index = int(index_str)

    context.user_data["selected_index"] = index

    buttons = [
        [InlineKeyboardButton("📥 Baixar este", callback_data="d|single")],
        [InlineKeyboardButton("📥 Baixar deste até o fim", callback_data="d|from")],
        [InlineKeyboardButton("📥 Baixar até aqui", callback_data="d|to")]
    ]
