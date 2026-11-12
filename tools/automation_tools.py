"""
Automation Tools - Desktop automation tools for JARVIS.
Registers desktop automation functions as tools.
"""
from core.plugin_system import tool, ToolCategory
from automation.desktop import (
    desk_list_windows,
    desk_activate_window,
    desk_get_mouse_position,
    desk_move_mouse,
    desk_click,
    desk_type_text,
    desk_hotkey,
    desk_screenshot,
    desk_locate_image,
    desk_click_image,
    desk_wait_for_image,
    desk_press_key,
    desk_drag,
)


@tool(
    description="Lista todas as janelas visíveis do Windows.",
    category=ToolCategory.SYSTEM,
)
async def list_windows() -> dict:
    """Lista todas as janelas visíveis com título, posição, tamanho e estado."""
    return await desk_list_windows()


@tool(
    description="Ativa (traz para frente) uma janela pelo título.",
    category=ToolCategory.SYSTEM,
)
async def activate_window(title: str) -> dict:
    """Ativa uma janela pelo título (busca parcial).

    Args:
        title: Título da janela (busca parcial)
    """
    return await desk_activate_window(title)


@tool(
    description="Obtém a posição atual do mouse.",
    category=ToolCategory.SYSTEM,
)
async def get_mouse_position() -> dict:
    """Retorna a posição atual do cursor do mouse (x, y)."""
    return await desk_get_mouse_position()


@tool(
    description="Move o mouse para uma posição absoluta.",
    category=ToolCategory.SYSTEM,
)
async def move_mouse(x: int, y: int, duration: float = 0.25) -> dict:
    """Move o cursor do mouse para coordenadas absolutas.

    Args:
        x: Coordenada X
        y: Coordenada Y
        duration: Duração do movimento em segundos
    """
    return await desk_move_mouse(x, y, duration)


@tool(
    description="Clica na posição atual ou em coordenadas específicas.",
    category=ToolCategory.SYSTEM,
)
async def click(x: int = None, y: int = None, button: str = "left", clicks: int = 1) -> dict:
    """Clica na posição atual ou nas coordenadas especificadas.

    Args:
        x: Coordenada X (opcional, usa posição atual se omitido)
        y: Coordenada Y (opcional, usa posição atual se omitido)
        button: Botão do mouse (left, right, middle)
        clicks: Número de cliques (1 ou 2 para duplo clique)
    """
    return await desk_click(x, y, button, clicks)


@tool(
    description="Digita texto no campo ativo.",
    category=ToolCategory.SYSTEM,
)
async def type_text(text: str, interval: float = 0.01) -> dict:
    """Digita o texto especificado no campo ativo.

    Args:
        text: Texto a ser digitado
        interval: Intervalo entre caracteres em segundos
    """
    return await desk_type_text(text, interval)


@tool(
    description="Pressiona uma combinação de teclas (hotkey).",
    category=ToolCategory.SYSTEM,
)
async def hotkey(*keys: str) -> dict:
    """Pressiona uma combinação de teclas.

    Args:
        keys: Teclas a pressionar (ex: 'ctrl', 'c' para Ctrl+C)
    """
    return await desk_hotkey(*keys)


@tool(
    description="Captura screenshot da tela ou região.",
    category=ToolCategory.SYSTEM,
)
async def screenshot(region: dict = None, save_path: str = None) -> dict:
    """Captura screenshot da tela inteira ou de uma região.

    Args:
        region: Região como dict com left, top, width, height (opcional)
        save_path: Caminho para salvar a imagem (opcional)
    """
    return await desk_screenshot(region, save_path)


@tool(
    description="Localiza uma imagem na tela.",
    category=ToolCategory.SYSTEM,
)
async def locate_image(image_path: str, confidence: float = 0.8, region: dict = None) -> dict:
    """Procura uma imagem na tela e retorna sua posição se encontrada.

    Args:
        image_path: Caminho da imagem a procurar
        confidence: Nível de confiança (0.0 a 1.0)
        region: Região de busca como dict com left, top, width, height (opcional)
    """
    return await desk_locate_image(image_path, confidence, region)


@tool(
    description="Localiza e clica em uma imagem na tela.",
    category=ToolCategory.SYSTEM,
)
async def click_image(image_path: str, confidence: float = 0.8) -> dict:
    """Procura uma imagem na tela e clica no centro se encontrada.

    Args:
        image_path: Caminho da imagem a procurar
        confidence: Nível de confiança (0.0 a 1.0)
    """
    return await desk_click_image(image_path, confidence)


@tool(
    description="Aguarda uma imagem aparecer na tela.",
    category=ToolCategory.SYSTEM,
)
async def wait_for_image(image_path: str, timeout: float = 10.0, confidence: float = 0.8) -> dict:
    """Aguarda até que uma imagem apareça na tela ou timeout.

    Args:
        image_path: Caminho da imagem a esperar
        timeout: Tempo máximo de espera em segundos
        confidence: Nível de confiança (0.0 a 1.0)
    """
    return await desk_wait_for_image(image_path, timeout, confidence)


@tool(
    description="Pressiona uma tecla única.",
    category=ToolCategory.SYSTEM,
)
async def press_key(key: str) -> dict:
    """Pressiona uma tecla única.

    Args:
        key: Nome da tecla (ex: 'enter', 'tab', 'esc', 'f1', 'space')
    """
    return await desk_press_key(key)


@tool(
    description="Arrasta o mouse de um ponto a outro.",
    category=ToolCategory.SYSTEM,
)
async def drag(x1: int, y1: int, x2: int, y2: int, duration: float = 0.5) -> dict:
    """Arrasta o mouse da posição (x1,y1) para (x2,y2).

    Args:
        x1: Coordenada X inicial
        y1: Coordenada Y inicial
        x2: Coordenada X final
        y2: Coordenada Y final
        duration: Duração do arrasto em segundos
    """
    return await desk_drag(x1, y1, x2, y2, duration)