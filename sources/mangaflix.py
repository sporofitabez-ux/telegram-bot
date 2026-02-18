# sources/mangaflix.py
import requests

class MangaFlixSource:
    BASE_URL = "https://api.mangaflix.net/v1"

    def search(self, query):
        try:
            url = f"{self.BASE_URL}/search/mangas?query={query}&selected_language=pt-br"
            resp = requests.get(url, timeout=10)
            data = resp.json().get("data", [])
            return [
                {"title": m.get("name"), "url": f"/br/manga/{m.get('_id')}"}
                for m in data
            ]
        except Exception:
            return []

    def chapters(self, manga_id):
        try:
            mid = manga_id.split("/")[-1]
            url = f"{self.BASE_URL}/mangas/{mid}"
            resp = requests.get(url, timeout=10)
            data = resp.json().get("data", {})
            return [
                {
                    "chapter_number": ch.get("number"),
                    "url": f"/br/manga/{ch.get('_id')}",
                    "manga_title": data.get("name", "Manga")
                }
                for ch in data.get("chapters", [])
            ]
        except Exception:
            return []

    def pages(self, chapter_id):
        try:
            cid = chapter_id.split("/")[-1]
            url = f"{self.BASE_URL}/chapters/{cid}?selected_language=pt-br"
            resp = requests.get(url, timeout=10)
            return [
                img.get("default_url")
                for img in resp.json().get("data", {}).get("images", [])
            ]
        except Exception:
            return []
