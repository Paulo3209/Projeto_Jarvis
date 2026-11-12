"""
JARVIS Main Entry Point - Supports CLI, GUI, and Voice modes.
Usage:
    python main.py              # CLI mode (default)
    python main.py --gui        # GUI mode with PyQt6 HUD
    python main.py --voice      # Voice mode (wake word: "jarvis") + interface holográfica
    python main.py --help       # Show help
"""
import asyncio
import sys
import argparse
import aioconsole
from core.brain import Brain
from core.event_bus import (
    EventBus,
    EventType,
    get_event_bus,
    UserMessageEvent,
    AssistantTokenEvent,
    AssistantResponseCompleteEvent,
    ToolCalledEvent,
    ToolCompletedEvent,
    ToolFailedEvent,
    MemorySavedEvent,
    MemoryRecalledEvent,
    ErrorEvent,
    StatusChangeEvent,
)
from core.personality import Personality, get_personality, apply_user_title, DEFAULT_PERSONALITY, MINIMAL_PERSONALITY, FRIENDLY_PERSONALITY, PersonalityProcessor
# Voice Gate import (lazy loaded in run_voice_mode)

# Config system
from config.settings import load_config, save_config


# Event handlers for demonstration (CLI mode)
def log_user_message(event: UserMessageEvent) -> None:
    print(f"\n[EVENT] User: {event.data['message'][:80]}...")


def log_assistant_token(event: AssistantTokenEvent) -> None:
    pass


def log_tool_called(event: ToolCalledEvent) -> None:
    print(f"\n[EVENT] Tool Called: {event.data['name']}({event.data['arguments']})")


def log_tool_completed(event: ToolCompletedEvent) -> None:
    result = event.data['result']
    status = "✓" if result.get('success') else "✗"
    msg = result.get('message', str(result)[:60])
    print(f"[EVENT] Tool Completed {status}: {event.data['name']} -> {msg}")


def log_tool_failed(event: ToolFailedEvent) -> None:
    print(f"[EVENT] Tool Failed ✗: {event.data['name']} -> {event.data['error']}")


def log_memory_saved(event: MemorySavedEvent) -> None:
    print(f"[EVENT] Memory Saved: {event.data['content'][:60]}...")


def log_memory_recalled(event: MemoryRecalledEvent) -> None:
    print(f"[EVENT] Memory Recalled: query='{event.data['query']}', found={len(event.data['memories'])}")


def log_error(event: ErrorEvent) -> None:
    print(f"[EVENT] Error: {event.data['error']}")


def log_status(event: StatusChangeEvent) -> None:
    print(f"[EVENT] Status: {event.data['status']}")


async def setup_event_listeners():
    """Register event listeners for demonstration."""
    bus = await get_event_bus()
    bus.subscribe(EventType.USER_MESSAGE, log_user_message)
    bus.subscribe(EventType.TOOL_CALLED, log_tool_called)
    bus.subscribe(EventType.TOOL_COMPLETED, log_tool_completed)
    bus.subscribe(EventType.TOOL_FAILED, log_tool_failed)
    bus.subscribe(EventType.MEMORY_SAVED, log_memory_saved)
    bus.subscribe(EventType.MEMORY_RECALLED, log_memory_recalled)
    bus.subscribe(EventType.ERROR, log_error)
    bus.subscribe(EventType.STATUS_CHANGE, log_status)


def select_personality() -> Personality:
    """Interactive personality selection."""
    print("\nSelecione a personalidade:")
    print("  1. Padrão (Formal, Conciso, Técnico, Humilde)")
    print("  2. Mínimo (Ultra-conciso, sem formatação)")
    print("  3. Amigável (Casual, com emojis)")
    print()

    while True:
        choice = input("Escolha [1-3] (padrão=1): ").strip()
        if choice in ("", "1"):
            return DEFAULT_PERSONALITY
        elif choice == "2":
            return MINIMAL_PERSONALITY
        elif choice == "3":
            return FRIENDLY_PERSONALITY
        else:
            print("Opção inválida. Tente novamente.")


async def run_cli_mode(personality: Personality):
    """Modo texto: persona J.A.R.V.I.S. + ferramentas (Ollama ou Gemini, com fallback)."""
    from core.jarvis_agent import JarvisAgent, system_report, time_greeting

    print("=" * 60)
    print("                 J.A.R.V.I.S. LEVEL 5")
    print("             Personal AI Agent - Windows")
    print("=" * 60)

    bus = await get_event_bus()
    bus.emit(StatusChangeEvent("online", source="main"))

    config = load_config()
    agent = JarvisAgent(personality, config)

    async def confirm_in_terminal(tool: str, args: dict) -> bool:
        print(f"\n[CONFIRMAÇÃO] J.A.R.V.I.S. quer executar: {tool}")
        print(f"   Argumentos: {args}")
        answer = (await aioconsole.ainput("   Autorizar? [s/N]: ")).strip().lower()
        return answer in ("s", "sim", "y", "yes")

    agent.confirm = confirm_in_terminal
    try:
        await agent.initialize()
    except RuntimeError as e:
        print(f"[ERRO] {e}")
        return

    title = personality.user_title
    print(f"JARVIS: {time_greeting(title)} {system_report(title)}\n")

    while True:
        try:
            user = (await aioconsole.ainput("Você: ")).strip()
            if not user:
                continue

            if user.lower() in {"sair", "exit", "quit"}:
                bus.emit(StatusChangeEvent("shutdown", source="main"))
                print(f"JARVIS: {personality.get_farewell()}")
                break
            if user.lower() in {"/reset", "/limpar"}:
                agent.reset()
                print("JARVIS: Contexto da conversa apagado.\n")
                continue

            print("\nJARVIS: ", end="", flush=True)
            async for token in agent.respond(user, spoken=False):
                print(token, end="", flush=True)
            print("\n")

        except (KeyboardInterrupt, EOFError):
            bus.emit(StatusChangeEvent("interrupted", source="main"))
            print(f"\nJARVIS: {personality.get_farewell()}")
            break

        except Exception as e:
            bus.emit(ErrorEvent(f"{type(e).__name__}: {e}", source="main"))
            print(f"\n[JARVIS ERROR] {type(e).__name__}: {e}\n")


async def run_voice_mode(personality: Personality, show_overlay: bool = True):
    """Modo voz estilo filme: wake word / 2 palmas -> interface holográfica -> conversa.

    Inclui: persona J.A.R.V.I.S., voz masculina, ações no PC/celular/rede com
    confirmação por voz, janela de conversa e modo espera.
    """
    from voice.assistant import JarvisVoiceAssistant
    from voice.clap_detector import ClapDetector, ClapConfig

    print("=" * 60)
    print("            J.A.R.V.I.S. LEVEL 5 - VOICE MODE")
    print("=" * 60)

    bus = await get_event_bus()
    bus.emit(StatusChangeEvent("online", source="main"))

    config = load_config()
    assistant = JarvisVoiceAssistant(personality, config, show_overlay=show_overlay)

    # ==================== CLAP DETECTOR ====================
    clap_detector = ClapDetector(ClapConfig(
        rms_threshold=config.get("clap_threshold", 0.08),
        min_clap_interval=0.15,
        max_clap_interval=1.0,
        cooldown_seconds=2.0,
    ))
    clap_detector.on_double_clap = assistant.on_double_clap
    if clap_detector.start():
        print("[CLAP] Detector de palmas ativo (2 palmas = ativa o JARVIS)")
    else:
        print("[CLAP] Aviso: detector de palmas não iniciou (verifique o microfone)")

    try:
        await assistant.run()
    except (KeyboardInterrupt, asyncio.CancelledError):
        print("\nEncerrando modo voz...")
    except Exception as e:
        print(f"\n[JARVIS ERROR] {type(e).__name__}: {e}")
    finally:
        clap_detector.stop()
        await assistant.shutdown()
        bus.emit(StatusChangeEvent("shutdown", source="main"))


async def run_gui_mode(personality: Personality):
    """Run in GUI mode with PyQt6 HUD."""
    try:
        from gui.bridge import run_gui_with_brain
    except ImportError as e:
        print(f"Erro ao importar GUI: {e}")
        print("Verifique se PyQt6 está instalado: pip install PyQt6")
        return 1

    brain = Brain(personality=personality)
    return await run_gui_with_brain(brain)


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="J.A.R.V.I.S. LEVEL 5 - Personal AI Agent",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python main.py              # CLI mode (interactive terminal)
  python main.py --gui        # GUI mode (PyQt6 HUD overlay)
  python main.py --voice      # Voice mode (wake word: "jarvis")
  python main.py --personality minimal  # Use minimal personality
        """
    )
    parser.add_argument(
        '--gui',
        action='store_true',
        help='Run in GUI mode with PyQt6 HUD overlay'
    )
    parser.add_argument(
        '--voice',
        action='store_true',
        help='Run in Voice mode (continuous listening, wake word: jarvis)'
    )
    parser.add_argument(
        '--personality', '-p',
        choices=['default', 'minimal', 'friendly'],
        default='default',
        help='Personality preset (default: default)'
    )
    parser.add_argument(
        '--no-overlay',
        action='store_true',
        help='Voice mode sem a interface holográfica'
    )
    parser.add_argument(
        '--no-events',
        action='store_true',
        help='Disable event logging in CLI mode'
    )
    return parser.parse_args()


async def main():
    args = parse_args()

    # Get personality (+ tratamento configurado: "senhor", "senhora", nome...)
    personality = apply_user_title(get_personality(args.personality), load_config().get("user_title"))

    if args.gui:
        # GUI mode
        return await run_gui_mode(personality)
    elif args.voice:
        # Voice mode
        return await run_voice_mode(personality, show_overlay=not args.no_overlay)
    else:
        # CLI mode
        if not args.no_events:
            await setup_event_listeners()
        await run_cli_mode(personality)
        return 0


if __name__ == "__main__":
    try:
        exit_code = asyncio.run(main())
        sys.exit(exit_code)
    except KeyboardInterrupt:
        print("\nEncerrando...")
        sys.exit(0)
    except Exception as e:
        print(f"\nErro fatal: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)