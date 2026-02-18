import httpx
import asyncio

class MangaFlixSource:
    name = "MangaFlix"
    base_url = "https://mangaflix.net"
    api_url = "https://api.mangaflix.net/v1"
    cdn_url = "https://cdn.mangaflix.net"

    async def search(self, query: str):
        url = f"{self.api_url}/search/mangas?query={query}&selected_language=pt-br"
        async with httpx.AsyncClient(timeout=60) as client:
            try:
                r = await client.get(url)
                r.raise_for_status()
                data = r.json()
            except Exception:
                return []

        results = []
        for item in data.get("data", []):
            results.append({
                "title": item.get("name"),
                "url": item.get("_id"),
            })
        return results

    async def chapters(self, manga_id: str):
        url = f"{self.api_url}/mangas/{manga_id}"
        async with httpx.AsyncClient(timeout=60) as client:
            try:
                r = await client.get(url)
                r.raise_for_status()
                data = r.json()
            except Exception:
                return []

        chapters = []
        manga_title = data.get("data", {}).get("name", "Manga")
        for ch in data.get("data", {}).get("chapters", []):
            chapters.append({
                "name": f"Capítulo {ch.get('number')}",
                "chapter_number": ch.get("number"),
                "url": ch.get("_id"),
                "manga_title": manga_title,
            })
        chapters.sort(key=lambda x: float(x.get("chapter_number") or 0), reverse=True)
        return chapters

    async def pages(self, chapter_id: str):
        url = f"{self.api_url}/chapters/{chapter_id}?selected_language=pt-br"
        async with httpx.AsyncClient(timeout=60) as client:
            try:
                r = await client.get(url)
                r.raise_for_status()
                data = r.json()
            except Exception:
                return []

        pages = []
        for p in data.get("data", {}).get("images", []):
            img_url = p.get("default_url")
            if img_url:
                pages.append(img_url)
        return pages
