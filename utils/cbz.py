import os
import zipfile
import tempfile
import shutil


def create_cbz(folder_path: str):
    """
    Cria um arquivo CBZ válido a partir de uma pasta de imagens.
    Retorna caminho do arquivo.
    """

    if not os.path.exists(folder_path):
        raise Exception("Pasta do capítulo não existe")

    images = sorted([
        f for f in os.listdir(folder_path)
        if f.lower().endswith((".jpg", ".jpeg", ".png", ".webp"))
    ])

    if not images:
        raise Exception("Nenhuma imagem encontrada para criar CBZ")

    # cria arquivo temporário
    fd, cbz_path = tempfile.mkstemp(suffix=".cbz")
    os.close(fd)

    with zipfile.ZipFile(cbz_path, "w", compression=zipfile.ZIP_STORED) as z:
        for img in images:
            abs_path = os.path.join(folder_path, img)
            z.write(abs_path, arcname=img)

    # remove pasta depois de zipar (economiza Railway disk)
    shutil.rmtree(folder_path, ignore_errors=True)

    # valida tamanho
    if os.path.getsize(cbz_path) < 1000:
        raise Exception("CBZ inválido criado")

    return cbz_path
