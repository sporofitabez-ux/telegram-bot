import zipfile
import httpx
import asyncio
from io import BytesIO


async def download_image(client, url):
    try:
        r = await client.get(url, timeout=60)
        r.raise_for_status()
        return r.content
    except Exception as e:
        print(f"Erro ao baixar imagem: {e}")
        return None


async def create_cbz(image_urls, manga_title, chapter_name):
    safe_title = manga_title.replace("/", "").replace(" ", "_")
    safe_chapter = str(chapter_name).replace("/", "").replace(" ", "_")

    cbz_filename = f"{safe_title}_{safe_chapter}.cbz"

    async with httpx.AsyncClient() as client:
        tasks = [download_image(client, url) for url in image_urls]
        images = await asyncio.gather(*tasks)

    images = [img for img in images if img]

    if not images:
        raise Exception("Nenhuma imagem foi baixada")

    # 🔥 CRIA CBZ NA MEMÓRIA
    cbz_buffer = BytesIO()

    with zipfile.ZipFile(cbz_buffer, "w", compression=zipfile.ZIP_DEFLATED) as cbz:
        for i, img_bytes in enumerate(images):
            cbz.writestr(f"{i+1}.jpg", img_bytes)

    cbz_buffer.seek(0)

    return cbz_buffer, cbz_filename
