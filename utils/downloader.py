import httpx
import asyncio

async def fetch_image(client, url):
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
        }
        r = await client.get(url, headers=headers, timeout=30.0)
        r.raise_for_status()
        return r.content
    except Exception as e:
        print(f"Erro ao baixar {url}: {e}")
        return None

async def download_images(urls):
    async with httpx.AsyncClient(http2=True, timeout=30.0) as client:
        tasks = [fetch_image(client, url) for url in urls]
        results = await asyncio.gather(*tasks)
        downloaded = [img for img in results if img]
        if not downloaded:
            print("Nenhuma imagem foi baixada")
        return downloaded
