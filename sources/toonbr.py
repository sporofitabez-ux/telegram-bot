import httpx
import asyncio

class ToonBrSource:
    name = "ToonBr"
    base_url = "https://beta.toonbr.com"
    api_url = "https://api.toonbr.com"
    cdn_url = "https://cdn2.toonbr.com"

    async def search(self, query: str):
        url = f"{self.api_url}/api/manga?page=1&limit=20&search={query}"
        async with httpx.AsyncClient(timeout=60) as client:
            try:
                r = await client.get(url)
                r.raise_for_status()
                data = r.json()
            except Exception:
                return []

        results = []
        for manga in data.get("data", []):
            results.append({
                "title": manga.get("title"),
                "url": manga.get("slug"),
            })
        return results

    async def chapters(self, manga_slug: str):
        url = f"{self.api_url}/api/manga/{manga_slug}"
        async with httpx.AsyncClient(timeout=60) as client:
            try:
                r = await client.get(url)
                r.raise_for_status()
                data = r.json()
            except Exception:
                return []

        chapters = []
        manga_title = data.get("title", "Manga")
        for ch in data.get("chapters", []):
            chapters.append({
                "name": ch.get("name"),
                "chapter_number": ch.get("chapterNumber"),
                "url": ch.get("id"),
                "manga_title": manga_title,
            })

        chapters.sort(key=lambda x: float(x.get("chapter_number") or 0), reverse=True)
        return chapters

    async def pages(self, chapter_id: str):
        url = f"{self.api_url}/api/chapter/{chapter_id}"
        async with httpx.AsyncClient(timeout=60) as client:
            try:
                r = await client.get(url)
                r.raise_for_status()
                data = r.json()
            except Exception:
                return []

        pages = []
        for p in data.get("pages", []):
            image = p.get("imageUrl")
            if image:
                pages.append(f"{self.cdn_url}{image}")
        return pages
