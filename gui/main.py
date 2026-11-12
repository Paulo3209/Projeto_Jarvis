"""
GUI Main Entry Point - Runs JARVIS with PyQt6 HUD interface.
"""
import asyncio
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.brain import Brain
from core.personality import get_personality, DEFAULT_PERSONALITY
from gui.bridge import run_gui_with_brain


async def main():
    """Main async entry point for GUI mode."""
    # Select personality (could be made interactive)
    personality = DEFAULT_PERSONALITY

    print("=" * 60)
    print("         J.A.R.V.I.S. LEVEL 5 - GUI MODE")
    print("=" * 60)
    print(f"Personalidade: {personality.name}")
    print("Iniciando interface gráfica...")
    print()

    # Create brain
    brain = Brain(personality=personality)

    # Run GUI with brain
    return await run_gui_with_brain(brain)


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