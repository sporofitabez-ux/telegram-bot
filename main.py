import os
import asyncio
import logging
import time

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

logging.basicConfig(level=logging.INFO)

DOWNLOAD_SEMAPHORE = asyncio.Semaphore(2)
CHAPTERS_PER_PAGE = 10
USER_COOLDOWN = {}
COOLDOWN_TIME = 5


# =====================================================
# ANTI SPAM
# =====================================================
def is_on_cooldown(user_id):
    now = time.time()
    last = USER_COOLDOWN.get(user_id, 0)

    if now - last < COOLDOWN_TIME:
        return True

    USER_COOLDOWN[user_id] = now
    return False


# =====================================================
# ENVIO DO CAPÍTULO
# =====================================================
async def send_chapter(message, source, chapter):

    async with DOWNLOAD_SEMAPHORE:

        cid = chapter.get("url")
        num = chapter.get("chapter_number")
        manga_title = chapter.get("manga_title", "Manga")

        try:
            imgs = await source.pages(cid)
            if not imgs:
                return

            cbz_buffer, cbz_name = await create_cbz(
                imgs,
                manga_title,
                f"Cap_{num}"
            )

            while True:
                try:
                    await message.reply_document(
                        document=cbz_buffer,
                        filename=cbz_name
                    )
                    break

                except RetryAfter as e:
                    await asyncio.sleep(int(e.retry_after) + 2)

                except (TimedOut, NetworkError):
                    await asyncio.sleep(5)

        except Exception as e:
            print(f"Erro capítulo {num}:", e)

        finally:
            try:
                cbz_buffer.close()
            except:
                pass


# =====================================================
# WORKER
# =====================================================
async def download_worker():

    print("✅ Worker Elite iniciado")

    while True:
        job = await DOWNLOAD_QUEUE.get()

        try:
            await send_chapter(
                job["message"],
                job["source"],
                job["chapter"],
            )

            await asyncio.sleep(2)

        except Exception as e:
            print("Erro no worker:", e)

        remove_job()
        DOWNLOAD_QUEUE.task_done()


# =====================================================
# BUSCAR
# =====================================================
async def buscar(update: Update, context: ContextTypes.DEFAULT_TYPE):

    user_id = update.effective_user.id

    if is_on_cooldown(user_id):
        return await update.message.reply_text("⏳ Aguarde alguns segundos.")

    if not context.args:
        return await update.message.reply_text(
            "Use: /buscar nome_do_manga"
        )

    query_text = " ".join(context.args)
    sources = get_all_sources()

    await update.message.reply_text(f"🔎 Buscando «{query_text}»")

    for source_name, source in sources.items():
        try:
            results = await source.search(query_text)
            if not results:
                continue

            manga = results[0]

            title = manga.get("title")
            url = manga.get("url")
            cover = manga.get("cover")
            status = manga.get("status", "Desconhecido")
            genres = manga.get("genres", "Não informado")
            synopsis = manga.get("synopsis", "Sem descrição.")

            chapters = await source.chapters(url)

            if not chapters:
                return await update.message.reply_text("❌ Nenhum capítulo encontrado.")

            # ordena automaticamente
            chapters.sort(key=lambda x: float(x.get("chapter_number", 0)))

            context.user_data["chapters"] = chapters
            context.user_data["source"] = source
            context.user_data["title"] = title
            context.user_data["page"] = 0

            caption = f"""📚 «{title}»

Status » {status}
Gênero: {genres}

Sinopse:
{synopsis}

🔗 @animesmangas308"""

            if cover:
                await update.message.reply_photo(photo=cover, caption=caption)
            else:
                await update.message.reply_text(caption)

            await send_chapter_page(update, context)
            return

        except Exception as e:
            print(f"Erro na fonte {source_name}:", e)

    await update.message.reply_text("❌ Nenhum resultado encontrado.")


# =====================================================
# PAGINAÇÃO
# =====================================================
async def send_chapter_page(update, context):

    chapters = context.user_data["chapters"]
    page = context.user_data["page"]

    start = page * CHAPTERS_PER_PAGE
    end = start + CHAPTERS_PER_PAGE

    keyboard = []

    for ch in chapters[start:end]:
        num = ch.get("chapter_number")
        keyboard.append([
            InlineKeyboardButton(
                f"Capítulo {num}",
                callback_data=f"cap_{num}"
            )
        ])

    nav_buttons = []

    if start > 0:
        nav_buttons.append(
            InlineKeyboardButton("⬅️", callback_data="prev")
        )

    if end < len(chapters):
        nav_buttons.append(
            InlineKeyboardButton("➡️", callback_data="next")
        )

    if nav_buttons:
        keyboard.append(nav_buttons)

    keyboard.append([
        InlineKeyboardButton("📥 Baixar todos", callback_data="all")
    ])

    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        "Escolha o capítulo:",
        reply_markup=reply_markup
    )


# =====================================================
# CALLBACKS
# =====================================================
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):

    query = update.callback_query
    await query.answer()

    chapters = context.user_data["chapters"]
    source = context.user_data["source"]

    if query.data == "next":
        context.user_data["page"] += 1
        await query.message.delete()
        await send_chapter_page(update, context)
        return

    if query.data == "prev":
        context.user_data["page"] -= 1
        await query.message.delete()
        await send_chapter_page(update, context)
        return

    if query.data == "all":
        for ch in chapters:
            await add_job({
                "message": query.message,
                "source": source,
                "chapter": ch,
            })

        await query.message.reply_text("✅ Todos capítulos adicionados.")
        return

    if query.data.startswith("cap_"):
        number = query.data.split("_")[1]

        for ch in chapters:
            if str(ch.get("chapter_number")) == number:
                await add_job({
                    "message": query.message,
                    "source": source,
                    "chapter": ch,
                })
                break

        await query.message.reply_text(f"✅ Capítulo {number} adicionado.")


# =====================================================
# STATUS
# =====================================================
async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"📦 Capítulos na fila: {queue_size()}"
    )


# =====================================================
# MAIN
# =====================================================
def main():

    app = ApplicationBuilder().token(
        os.getenv("BOT_TOKEN")
    ).build()

    app.add_handler(CommandHandler("buscar", buscar))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CallbackQueryHandler(button_handler))

    async def startup(app):
        asyncio.create_task(download_worker())
        print("✅ Worker iniciado")

    app.post_init = startup

    print("🤖 Bot iniciado...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
