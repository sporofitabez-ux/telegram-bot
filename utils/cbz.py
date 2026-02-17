import os
import zipfile
import httpx
import tempfile
import asyncio
import re

def sanitize_filename(name):
    return re.sub(r'[\\/*?:"<>|]', "", name)

async def create_cbz(images, manga_title, chapter_name, progress_message=None):
    temp_dir = tempfile.mkdtemp()
    async with httpx.AsyncClient(timeout=60) as client:
        for idx, img_url in enumerate(images):
            await download_image(client, img_url, temp_dir, idx)
            if progress_message:
                await progress_message.edit_text(f"📦 Baixando {idx+1}/{len(images)} páginas...")

    safe_title = sanitize_filename(manga_title)
    safe_chapter = sanitize_filename(chapter_name)
    cbz_name = f"{safe_title} - {safe_chapter}.cbz"
    cbz_path = os.path.join(temp_dir, cbz_name)

    with zipfile.ZipFile(cbz_path, "w", compression=zipfile.ZIP_DEFLATED) as cbz:
        for file in sorted(os.listdir(temp_dir)):
            if file.endswith(".jpg"):
                cbz.write(os.path.join(temp_dir, file), arcname=file)

    return cbz_path, cbz_name

async def download_image(client, url, folder, index):
    try:
        r = await client.get(url)
        file_path = os.path.join(folder, f"{index:03d}.jpg")
        with open(file_path, "wb") as f:
            f.write(r.content)
    except Exception:
        pass
