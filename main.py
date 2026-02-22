import os
import asyncio
import logging

from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
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


# ================= SEND =================
async def send_chapter(message, source, chapter):

    async with DOWNLOAD_SEMAPHORE:

        cid = chapter.get("url")
        num = chapter.get("chapter_number")
        manga_title = chapter.get("manga_title", "Manga")

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

        cbz_buffer.close()


# ================= WORKER =================
async def download_worker(app):

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
            print("Erro worker:", e)

        remove_job()
        DOWNLOAD_QUEUE.task_done()


async def start_worker(app):
    asyncio.create_task(download_worker(app))


# ================= COMMANDS =================
async def buscar(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if not context.args:
        return await update.message.reply_text("/buscar nome")

    query = " ".join(context.args)

    source_name, source = list(get_all_sources().items())[0]

    mangas = await source.search(query)

    manga = mangas[0]
    chapters = await source.chapters(manga["url"])

    await update.message.reply_text(
        f"📥 {len(chapters)} capítulos adicionados na fila."
    )

    for ch in chapters:
        await add_job({
            "message": update.message,
            "source": source,
            "chapter": ch,
            "meta": {
                "title": manga["title"],
                "chapter": ch.get("chapter_number")
            }
        })


async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"📦 Capítulos na fila: {queue_size()}"
    )


async def cancelar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    while not DOWNLOAD_QUEUE.empty():
        DOWNLOAD_QUEUE.get_nowait()
        DOWNLOAD_QUEUE.task_done()

    await update.message.reply_text("❌ Fila cancelada.")


# ================= MAIN =================
def main():

    app = ApplicationBuilder().token(os.getenv("BOT_TOKEN")).build()

    app.add_handler(CommandHandler("buscar", buscar))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("cancelar", cancelar))

    app.post_init = start_worker

    app.run_polling()


if __name__ == "__main__":
    main()
