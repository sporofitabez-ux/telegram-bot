from sources.toonbr import ToonBrSource
from sources.mangaflix import MangaFlixSource

def get_all_sources():
    return {
        "ToonBr": ToonBrSource(),
        "MangaFlix": MangaFlixSource()
    }
