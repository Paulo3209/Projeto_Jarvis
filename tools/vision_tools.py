"""
Vision Tools - Computer vision tools for JARVIS.
Registers camera, screen, OCR, and detection functions as tools.
"""
from core.plugin_system import tool, ToolCategory


# ===== Camera Tools =====

@tool(
    description="Abre a webcam com configurações específicas.",
    category=ToolCategory.SYSTEM,
)
async def camera_open(device_index: int = 0, width: int = 1280, height: int = 720, fps: int = 30) -> dict:
    """Abre a webcam.

    Args:
        device_index: Índice da câmera (0 = padrão)
        width: Largura da resolução
        height: Altura da resolução
        fps: Frames por segundo
    """
    from vision.camera import camera_open as _camera_open
    return await _camera_open(device_index, width, height, fps)


@tool(
    description="Fecha a webcam.",
    category=ToolCategory.SYSTEM,
)
async def camera_close() -> dict:
    """Fecha a webcam."""
    from vision.camera import camera_close as _camera_close
    return await _camera_close()


@tool(
    description="Captura um frame da webcam.",
    category=ToolCategory.SYSTEM,
)
async def camera_capture(save_path: str = None, format: str = "jpg") -> dict:
    """Captura um frame da webcam.

    Args:
        save_path: Caminho para salvar a imagem (opcional)
        format: Formato da imagem (jpg, png)
    """
    from vision.camera import camera_capture as _camera_capture
    return await _camera_capture(save_path, format)


@tool(
    description="Lista câmeras disponíveis.",
    category=ToolCategory.SYSTEM,
)
async def camera_list() -> dict:
    """Lista todas as câmeras disponíveis."""
    from vision.camera import camera_list as _camera_list
    return await _camera_list()


@tool(
    description="Obtém propriedades da câmera.",
    category=ToolCategory.SYSTEM,
)
async def camera_get_properties() -> dict:
    """Obtém propriedades atuais da câmera (brilho, contraste, exposição, etc.)."""
    from vision.camera import camera_get_properties as _camera_get_properties
    return await _camera_get_properties()


@tool(
    description="Define propriedade da câmera.",
    category=ToolCategory.SYSTEM,
)
async def camera_set_property(name: str, value: float) -> dict:
    """Define uma propriedade da câmera.

    Args:
        name: Nome da propriedade (brightness, contrast, saturation, exposure, focus, etc.)
        value: Valor da propriedade
    """
    from vision.camera import camera_set_property as _camera_set_property
    return await _camera_set_property(name, value)


@tool(
    description="Inicia streaming contínuo da webcam.",
    category=ToolCategory.SYSTEM,
)
async def camera_start_stream() -> dict:
    """Inicia captura contínua da webcam em background."""
    from vision.camera import camera_start_stream as _camera_start_stream
    return await _camera_start_stream()


@tool(
    description="Para streaming contínuo da webcam.",
    category=ToolCategory.SYSTEM,
)
async def camera_stop_stream() -> dict:
    """Para captura contínua da webcam."""
    from vision.camera import camera_stop_stream as _camera_stop_stream
    return await _camera_stop_stream()


# ===== Screen Capture Tools =====

@tool(
    description="Captura a tela (monitor inteiro ou região).",
    category=ToolCategory.SYSTEM,
)
async def screen_capture(monitor: int = 0, region: dict = None, save_path: str = None) -> dict:
    """Captura a tela.

    Args:
        monitor: Índice do monitor (0 = todos, 1+ = monitor específico)
        region: Região como dict {left, top, width, height} (opcional)
        save_path: Caminho para salvar (opcional)
    """
    from vision.screen import screen_capture as _screen_capture
    return await _screen_capture(monitor, region, save_path)


@tool(
    description="Captura uma janela específica pelo título.",
    category=ToolCategory.SYSTEM,
)
async def screen_capture_window(window_title: str, save_path: str = None) -> dict:
    """Captura janela específica.

    Args:
        window_title: Título da janela (busca parcial)
        save_path: Caminho para salvar (opcional)
    """
    from vision.screen import screen_capture_window as _screen_capture_window
    return await _screen_capture_window(window_title, save_path)


@tool(
    description="Lista monitores disponíveis.",
    category=ToolCategory.SYSTEM,
)
async def screen_list_monitors() -> dict:
    """Lista monitores detectados."""
    from vision.screen import screen_list_monitors as _screen_list_monitors
    return await _screen_list_monitors()


@tool(
    description="Inicia captura contínua da tela.",
    category=ToolCategory.SYSTEM,
)
async def screen_start_stream(monitor: int = 0, region: dict = None, fps: float = 10) -> dict:
    """Inicia streaming de tela.

    Args:
        monitor: Índice do monitor
        region: Região como dict {left, top, width, height}
        fps: Frames por segundo
    """
    from vision.screen import screen_start_stream as _screen_start_stream
    return await _screen_start_stream(monitor, region, fps)


@tool(
    description="Para captura contínua da tela.",
    category=ToolCategory.SYSTEM,
)
async def screen_stop_stream() -> dict:
    """Para streaming de tela."""
    from vision.screen import screen_stop_stream as _screen_stop_stream
    return await _screen_stop_stream()


# ===== OCR Tools =====

@tool(
    description="Extrai texto da tela ou imagem (OCR).",
    category=ToolCategory.SYSTEM,
)
async def screen_ocr(image_path: str = None, lang: str = "por+eng", region: dict = None) -> dict:
    """Extrai texto via OCR (Tesseract).

    Args:
        image_path: Caminho de imagem (se omitido, captura tela)
        lang: Idiomas (ex: por+eng, eng, spa)
        region: Região da tela como dict {left, top, width, height}
    """
    from vision.screen import screen_ocr as _screen_ocr
    return await _screen_ocr(image_path, lang, region)


@tool(
    description="Extrai texto com posições e confiança (OCR detalhado).",
    category=ToolCategory.SYSTEM,
)
async def screen_ocr_detailed(image_path: str = None, lang: str = "por+eng", region: dict = None) -> dict:
    """OCR com detalhes de posição e confiança.

    Args:
        image_path: Caminho de imagem (opcional)
        lang: Idiomas
        region: Região da tela
    """
    from vision.screen import screen_ocr_detailed as _screen_ocr_detailed
    return await _screen_ocr_detailed(image_path, lang, region)


@tool(
    description="Busca texto específico na tela.",
    category=ToolCategory.SYSTEM,
)
async def screen_find_text(search_text: str, lang: str = "por+eng", region: dict = None) -> dict:
    """Procura texto específico na tela.

    Args:
        search_text: Texto a buscar
        lang: Idiomas
        region: Região da tela
    """
    from vision.screen import screen_find_text as _screen_find_text
    return await _screen_find_text(search_text, lang, region)


# ===== Template Matching Tools =====

@tool(
    description="Carrega imagem de referência para busca (template matching).",
    category=ToolCategory.SYSTEM,
)
async def screen_load_template(template_path: str, name: str = None) -> dict:
    """Carrega template para busca visual.

    Args:
        template_path: Caminho da imagem template
        name: Nome identificador (opcional, usa nome do arquivo)
    """
    from vision.screen import screen_load_template as _screen_load_template
    return await _screen_load_template(template_path, name)


@tool(
    description="Busca template na tela.",
    category=ToolCategory.SYSTEM,
)
async def screen_find_template(template_name: str, threshold: float = 0.8, region: dict = None) -> dict:
    """Procura template carregado na tela.

    Args:
        template_name: Nome do template carregado
        threshold: Limiar de correspondência (0.0 a 1.0)
        region: Região de busca
    """
    from vision.screen import screen_find_template as _screen_find_template
    return await _screen_find_template(template_name, threshold, region)


# ===== Object Detection Tools =====

@tool(
    description="Carrega modelo YOLO para detecção de objetos.",
    category=ToolCategory.SYSTEM,
)
async def detector_load_model(model_path: str = "yolov8n.pt", device: str = "auto", conf: float = 0.5) -> dict:
    """Carrega modelo YOLO.

    Args:
        model_path: Caminho do modelo (yolov8n.pt, yolov8s.pt, yolov8m.pt, yolov8l.pt, yolov8x.pt ou custom)
        device: Dispositivo (auto, cpu, cuda, mps)
        conf: Threshold de confiança
    """
    from vision.detector import detector_load_model as _detector_load_model
    return await _detector_load_model(model_path, device, conf)


@tool(
    description="Descarrega modelo YOLO da memória.",
    category=ToolCategory.SYSTEM,
)
async def detector_unload_model() -> dict:
    """Libera modelo YOLO da memória."""
    from vision.detector import detector_unload_model as _detector_unload_model
    return await _detector_unload_model()


@tool(
    description="Detecta objetos na tela ou imagem.",
    category=ToolCategory.SYSTEM,
)
async def detector_detect(image_path: str = None, classes: list = None, min_conf: float = None) -> dict:
    """Executa detecção de objetos.

    Args:
        image_path: Caminho da imagem (opcional, senão captura tela)
        classes: Filtrar classes específicas (ex: ["person", "cell phone", "laptop"])
        min_conf: Confiança mínima
    """
    from vision.detector import detector_detect as _detector_detect
    return await _detector_detect(image_path, classes, min_conf)


@tool(
    description="Detecta objetos e salva imagem anotada.",
    category=ToolCategory.SYSTEM,
)
async def detector_detect_and_annotate(image_path: str, output_path: str = None) -> dict:
    """Detecta e desenha caixas na imagem.

    Args:
        image_path: Imagem de entrada
        output_path: Onde salvar imagem anotada
    """
    from vision.detector import detector_detect_and_annotate as _detector_detect_and_annotate
    return await _detector_detect_and_annotate(image_path, output_path)


@tool(
    description="Lista classes disponíveis no modelo YOLO.",
    category=ToolCategory.SYSTEM,
)
async def detector_get_classes() -> dict:
    """Retorna mapeamento de IDs para nomes de classes."""
    from vision.detector import detector_get_classes as _detector_get_classes
    return await _detector_get_classes()


@tool(
    description="Detecta rostos na imagem.",
    category=ToolCategory.SYSTEM,
)
async def face_detect(image_path: str = None, use_yolo: bool = False) -> dict:
    """Detecção facial.

    Args:
        image_path: Imagem (opcional, senão tela)
        use_yolo: Usar YOLO face (requer modelo yolov8n-face.pt)
    """
    from vision.detector import face_detect as _face_detect
    return await _face_detect(image_path, use_yolo)


@tool(
    description="Detecta movimento entre frames.",
    category=ToolCategory.SYSTEM,
)
async def motion_detect(threshold: int = 25, min_area: int = 500, image_path: str = None) -> dict:
    """Detecção de movimento por diferença de frames.

    Args:
        threshold: Limiar de diferença de pixel
        min_area: Área mínima do movimento
        image_path: Imagem (opcional, senão tela)
    """
    from vision.detector import motion_detect as _motion_detect
    return await _motion_detect(threshold, min_area, image_path)


@tool(
    description="Reseta detector de movimento.",
    category=ToolCategory.SYSTEM,
)
async def motion_reset() -> dict:
    """Reseta modelo de fundo do detector de movimento."""
    from vision.detector import motion_reset as _motion_reset
    return await _motion_reset()