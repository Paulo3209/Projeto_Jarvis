from tools.system import AVAILABLE_FUNCTIONS


class Router:

    def execute(self, function_name, arguments=None):
        arguments = arguments or {}

        function = AVAILABLE_FUNCTIONS.get(function_name)

        if not function:
            return {
                "success": False,
                "message": f"Ferramenta '{function_name}' não encontrada."
            }

        try:
            return function(**arguments)

        except Exception as error:
            return {
                "success": False,
                "message": f"Erro ao executar {function_name}: {error}"
            }