import asyncio
from .job_manager import MangaJob

download_queue = asyncio.Queue()
current_job = None


async def worker():
    global current_job

    while True:
        job = await download_queue.get()
        current_job = job
        job.status = "downloading"

        try:
            await process_job(job)
            job.status = "completed"
        except Exception as e:
            job.status = "error"
            print("Erro no job:", e)

        current_job = None
        download_queue.task_done()


async def process_job(job):
    from utils.cbz import create_cbz

    for chapter in job.chapters:

        if job.cancelled:
            job.status = "cancelled"
            return

        imgs = await job.source.pages(chapter["url"])
        if not imgs:
            continue

        cbz_path, cbz_name = await create_cbz(
            imgs,
            chapter.get("manga_title", "Manga"),
            f"Cap_{chapter.get('chapter_number')}"
        )

        await job.message.reply_document(
            document=open(cbz_path, "rb"),
            filename=cbz_name
        )

        import os
        os.remove(cbz_path)

        job.update_progress()
