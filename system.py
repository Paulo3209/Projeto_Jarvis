import subprocess


def open_notepad():
    subprocess.Popen(["notepad.exe"])

    return {
        "success": True,
        "message": "Bloco de Notas aberto com sucesso."
    }


def open_calculator():
    subprocess.Popen(["calc.exe"])

    return {
        "success": True,
        "message": "Calculadora aberta com sucesso."
    }


AVAILABLE_FUNCTIONS = {
    "open_notepad": open_notepad,
    "open_calculator": open_calculator,
}