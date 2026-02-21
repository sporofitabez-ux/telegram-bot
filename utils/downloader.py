import httpx
import asyncio
import os
import tempfile


HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Referer": "https://mangaflix.net/",
    "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8"
}


async def fetch_image(client, url):
    try:
        r = await client.get(url, headers=HEADERS, timeout=60.0)
        if r.status_code != 200:
            print("Falha imagem:", r.status_code, url)
            return None
        return r.content
    except Exception as e:
        print("Erro imagem:", e, url)
        return None


async def download_chapter(source, chapter):
    # pega páginas do source
    pages = await source.pages(chapter["url"])

    if not pages:
        raise Exception("Sem páginas")

    async with httpx.AsyncClient(http2=True, timeout=60.0) as client:
        tasks = [fetch_image(client, url) for url in pages]
        images = await asyncio.gather(*tasks)

    images = [img for img in images if img]

    if not images:
        raise Exception("Nenhuma imagem baixada")

    folder = tempfile.mkdtemp(prefix="manga_")

    for i, img in enumerate(images):
        with open(os.path.join(folder, f"{i:03}.jpg"), "wb") as f:
            f.write(img)

    return folder
