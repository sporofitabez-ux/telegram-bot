from sources.toonbr import ToonBrSource
from sources.mangaflix import MangaFlixSource

# fontes disponíveis
_sources = {
    "ToonBr": ToonBrSource(),
    "MangaFlix": MangaFlixSource()
}

def get_all_sources():
    return _sources
