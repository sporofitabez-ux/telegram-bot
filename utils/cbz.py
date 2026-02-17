import os
import zipfile
import aiohttp
import tempfile
import asyncio
import re

def sanitize_filename(name):
    return re.sub(r'[\\/*?:"<>|]', "", name)

async def download_image(session, url, path):
    try:
        async with session.get(url) as resp:
            if resp.status == 200:
                content = await resp.read()
                with open(path, "wb") as f:
                    f.write(content)
    except Exception:
        pass

async def create_cbz(images, manga_title, chapter_name):
    temp_dir = tempfile.mkdtemp()
    async with aiohttp.ClientSession() as session:
        tasks = []
        for idx, img_url in enumerate(images):
            ext = os.path.splitext(img_url)[1].split("?")[0] or ".jpg"
            p = os.path.join(temp_dir, f"{idx:03d}{ext}")
            tasks.append(download_image(session, img_url, p))
        await asyncio.gather(*tasks)

    safe_title = sanitize_filename(manga_title)
    safe_chap = sanitize_filename(chapter_name)
    cbz_name = f"{safe_title} - {safe_chap}.cbz"
    cbz_path = os.path.join(temp_dir, cbz_name)

    with zipfile.ZipFile(cbz_path, "w", compression=zipfile.ZIP_DEFLATED) as cbz:
        for file in sorted(os.listdir(temp_dir)):
            if file.endswith(".jpg") or file.endswith(".png"):
                cbz.write(os.path.join(temp_dir, file), arcname=file)

    return cbz_path, cbz_name
