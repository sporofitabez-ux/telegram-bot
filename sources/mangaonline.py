import httpx
from bs4 import BeautifulSoup
from urllib.parse import urljoin

BASE_URL = "https://mangasonline.blog"


class MangaOnlineSource:

    def __init__(self):
        self.client = httpx.AsyncClient(timeout=30)

    # ================= POPULAR =================

    async def popular(self):
        url = f"{BASE_URL}/manga/"
        r = await self.client.get(url)
        soup = BeautifulSoup(r.text, "html.parser")

        mangas = []

        for item in soup.select(".post-title a"):
            mangas.append({
                "title": item.text.strip(),
                "url": item["href"]
            })

        return mangas

    # ================= SEARCH =================

    async def search(self, query):
        url = f"{BASE_URL}/?s={query}&post_type=wp-manga"
        r = await self.client.get(url)
        soup = BeautifulSoup(r.text, "html.parser")

        mangas = []

        for item in soup.select(".post-title a"):
            mangas.append({
                "title": item.text.strip(),
                "url": item["href"]
            })

        return mangas

    # ================= DETAILS =================

    async def details(self, manga_url):
        r = await self.client.get(manga_url)
        soup = BeautifulSoup(r.text, "html.parser")

        description = ""
        desc = soup.select_one(".summary__content")
        if desc:
            description = desc.text.strip()

        return {
            "description": description
        }

    # ================= CHAPTERS =================

    async def chapters(self, manga_url):
        r = await self.client.get(manga_url)
        soup = BeautifulSoup(r.text, "html.parser")

        chapters = []

        for ch in soup.select(".wp-manga-chapter a"):
            chapters.append({
                "name": ch.text.strip(),
                "url": ch["href"]
            })

        # Reverter (igual extensão)
        chapters.reverse()

        return chapters

    # ================= PAGES =================

    async def pages(self, chapter_url):
        r = await self.client.get(chapter_url)
        soup = BeautifulSoup(r.text, "html.parser")

        images = []

        for img in soup.select(".reading-content img"):
            src = img.get("data-src") or img.get("src")
            if src:
                images.append(src)

        return images
