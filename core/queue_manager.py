import asyncio

download_queue = asyncio.Queue()
current_job = None


async def worker():
    global current_job

    while True:
        job = await download_queue.get()
        current_job = job

        try:
            await job.run()
        except Exception as e:
            print("Erro geral no job:", e)
        finally:
            current_job = None
            download_queue.task_done()
