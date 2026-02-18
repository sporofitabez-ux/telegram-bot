import httpx

class MangaFlixSource:
    name = "MangaFlix"
    base_url = "https://mangaflix.net"
    api_url = "https://api.mangaflix.net/v1"
    cdn_url = ""

    async def search(self, query: str):
        url = f"{self.api_url}/search/mangas?query={query}&selected_language=pt-br"
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.get(url)
            r.raise_for_status()
            data = r.json()
        results = []
        for manga in data.get("data", []):
            results.append({
                "title": manga.get("name"),
                "url": manga.get("_id"),
            })
        return results

    async def chapters(self, manga_id: str):
        url = f"{self.api_url}/mangas/{manga_id}"
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.get(url)
            r.raise_for_status()
            data = r.json()
        manga_title = data.get("data", {}).get("name", "Manga")
        chapters = []
        for ch in data.get("data", {}).get("chapters", []):
            chapters.append({
                "name": ch.get("name"),
                "chapter_number": ch.get("number"),
                "url": ch.get("_id"),
                "manga_title": manga_title
            })
        chapters.sort(key=lambda x: float(x.get("chapter_number") or 0), reverse=True)
        return chapters

    async def pages(self, chapter_id: str):
        url = f"{self.api_url}/chapters/{chapter_id}?selected_language=pt-br"
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.get(url)
            r.raise_for_status()
            data = r.json()
        pages = [img.get("default_url") for img in data.get("data", {}).get("images", []) if img.get("default_url")]
        return pages
