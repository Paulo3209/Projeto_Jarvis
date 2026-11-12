"""
Reflexos do J.A.R.V.I.S.: comandos frequentes executados na hora, sem IA.

"Abra o Chrome", "pause a música", "aumente o volume", "feche o Word",
"mostre a área de trabalho", "status do sistema", "que horas são"...
Resposta em < 1 s em vez de 20-60 s do modelo local. Pedidos compostos ou
ambíguos ("abra o Chrome e pesquise X", "abra o arquivo Y") vão para a IA.
"""
from __future__ import annotations

import asyncio
import re
import unicodedata
from datetime import datetime
from typing import Optional

WEEKDAYS = ["segunda-feira", "terça-feira", "quarta-feira", "quinta-feira", "sexta-feira", "sábado", "domingo"]
MONTHS = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto",
          "setembro", "outubro", "novembro", "dezembro"]

_OPEN = r"(?:abr[ae]|abrir|abre|inici[ae]|iniciar|execut[ae]|lanc[ae]|bota|coloca|poe|ponha|entr[ae] n[oa])"
_CLOSE = r"(?:fech[ae]|fechar|encerr[ae]|sai[ar]? d[oa])"
_ART = r"(?:(?:o|a|os|as|um|uma|meu|minha)\s+)?"
_POLITE = r"^(?:(?:por favor|pfv|pode|voce pode|poderia|consegue|quero que voce|preciso que voce)\s+)*"
_WEB_HINTS = ("site", "youtube", "gmail", "netflix", "instagram", "facebook", "twitter", "github", "chatgpt",
              "linkedin", "mercado livre", "amazon", "google maps", "maps", "tradutor", "whatsapp web", ".com", ".br")


def _norm(text: str) -> str:
    text = unicodedata.normalize("NFD", text.lower())
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s.]", " ", text)).strip(" .")


class Reflexes:
    def __init__(self, title: str = "senhor", dry_run: bool = False):
        self.title = title
        self.dry_run = dry_run   # testes: interpreta sem executar
        self.last_call: Optional[tuple] = None

    async def handle(self, text: str) -> Optional[str]:
        """Executa o reflexo e devolve a frase a falar; None = deixar para a IA."""
        n = re.sub(_POLITE, "", _norm(text))
        n = re.sub(r"\s+(?:para mim|pra mim|por favor|agora|ai)$", "", n).strip()
        t = self.title

        # Compostos ("abra X e pesquise Y") ou com arquivos/pastas -> IA
        if re.search(r"\be (depois|entao|pesquis|procur|busc|digit|escrev|toc|coloc|mand|envi)", n) or \
                re.search(r"\b(arquivo|pasta|documento|planilha)\b", n):
            return None

        # ---- Horas / data / status
        if re.search(r"\b(que horas|que hora e|horas sao)\b", n):
            now = datetime.now()
            return f"São {now.hour} e {now.minute:02d}, {t}." if now.minute else f"São {now.hour} em ponto, {t}."
        if re.search(r"\b(que dia e hoje|que dia e|data de hoje|qual a data)\b", n):
            now = datetime.now()
            return f"Hoje é {WEEKDAYS[now.weekday()]}, {now.day} de {MONTHS[now.month - 1]}."
        if re.search(r"\b(status|diagnostico|relatorio)\b.*\b(sistema|pc|computador|maquina)?\b", n) and \
                len(n.split()) <= 6 or re.search(r"\bcomo (esta|estao) o(s)? (sistema|pc|computador)", n):
            from core.jarvis_agent import system_report
            return system_report(t)

        # ---- Recursos específicos (memória, CPU, disco, bateria) e janelas abertas
        resource = self._resources(n)
        if resource:
            return resource
        if re.search(r"\b(quais|que) (janelas|programas|apps|aplicativos)\b.*\babert", n):
            from core.plugin_system import get_tool
            res = await get_tool("list_windows").function()
            titles = []
            for w in (res.get("windows") or []):
                title = (w.get("title") or "").split(" - ")[-1].strip()
                if title and title not in titles:
                    titles.append(title)
            if not titles:
                return f"Não há janelas abertas, {t}."
            top = ", ".join(titles[:4])
            more = f", e mais {len(titles) - 4}" if len(titles) > 4 else ""
            return f"{len(titles)} janelas abertas, {t}: {top}{more}."

        # ---- Aparelhos na rede
        if re.search(r"\b(aparelhos?|dispositivos?|equipamentos?|quem)\b.*\b(rede|wi ?fi|conectad)", n):
            from core.plugin_system import get_tool
            print("[JARVIS] Reflexo: lan_devices()")
            if self.dry_run:
                self.last_call = ("lan_devices", {})
                return "Varredura simulada."
            res = await get_tool("lan_devices").function()
            devs = res.get("devices", [])
            if not devs:
                return f"Não encontrei outros aparelhos na rede, {t}."
            kinds = {}
            for d in devs:
                kinds[d["kind"] or "outros"] = kinds.get(d["kind"] or "outros", 0) + 1
            parts = []
            for label, key in (("computadores", "computador"), ("prováveis celulares ou tablets", "provável celular/tablet"),
                               ("com depuração Android ativa", "android (ADB ativo)"), ("outros aparelhos", "outros")):
                if kinds.get(key):
                    parts.append(f"{kinds[key]} {label}")
            ssh = sum(1 for d in devs if "ssh" in d["control"])
            extra = f" {ssh} aceita{'m' if ssh > 1 else ''} SSH." if ssh else ""
            return f"Encontrei {len(devs)} aparelhos na rede, {t}: " + ", ".join(parts) + "." + extra

        # ---- Mídia / volume
        media = self._media(n)
        if media:
            return await self._run("media_control", media[0], media[1])

        if re.search(r"\b(minimiz\w* tudo|mostr\w* a area de trabalho|area de trabalho)\b", n):
            return await self._run("show_desktop", {}, f"Pronto, {t}.")

        # ---- Abrir app / site
        m = re.match(rf"^{_OPEN}\s+{_ART}(?P<x>.+)$", n)
        if m:
            target = re.sub(r"^(?:aplicativo|app|programa)\s+(?:d[oa]\s+)?", "", m.group("x")).strip()
            if not target or len(target.split()) > 4 or " e " in f" {target} ":
                return None
            if any(h in target for h in _WEB_HINTS):
                site = re.sub(r"^(?:o\s+)?site\s+(?:d[oa]\s+)?", "", target)
                return await self._run("open_site", {"target": site}, f"Abrindo {site}, {t}.")
            reply = await self._run("launch_app", {"name": target}, f"Abrindo {target}, {t}.", quiet=True)
            if reply:
                return reply
            # Não é app instalado: tenta como site conhecido
            from tools.launcher import SITES
            if target in SITES:
                return await self._run("open_site", {"target": target}, f"Abrindo {target}, {t}.")
            return None  # não é app instalado nem site conhecido: a IA decide

        # ---- Fechar app
        m = re.match(rf"^{_CLOSE}\s+{_ART}(?P<x>.+)$", n)
        if m and len(m.group("x").split()) <= 3:
            target = m.group("x")
            return await self._run("close_app", {"name": target}, f"Fechando {target}, {t}.",
                                   fail=f"Não há nenhuma janela de {target} aberta, {t}.")

        # ---- Captura de tela
        if re.search(r"\b(tir\w* (um )?print|captur\w* (a )?tela|screenshot)\b", n):
            return await self._run("screenshot", {}, f"Captura de tela salva, {t}.")
        return None

    def _resources(self, n: str) -> Optional[str]:
        """Perguntas sobre memória/CPU/disco/bateria respondidas direto pelo psutil."""
        if not re.search(r"\b(quant\w*|qual|como|uso|usando|esta|nivel|status)\b", n):
            return None
        if re.search(r"\b(celular|telefone|android)\b", n):
            return None  # bateria do celular -> IA/ADB
        import psutil
        t = self.title
        if re.search(r"\b(memoria|ram)\b", n):
            vm = psutil.virtual_memory()
            used, total = vm.used / 2**30, vm.total / 2**30
            used_txt = f"{used:.1f}".replace(".", ",")
            msg = f"A memória está em {vm.percent:.0f} por cento, {t}: {used_txt} de {total:.0f} gigabytes."
            if vm.percent >= 90:
                top = sorted(psutil.process_iter(["name", "memory_info"]),
                             key=lambda p: p.info["memory_info"].rss if p.info.get("memory_info") else 0,
                             reverse=True)[:1]
                if top:
                    msg += f" O maior consumidor é {top[0].info['name'].removesuffix('.exe')}."
            return msg
        if re.search(r"\b(cpu|processador)\b", n):
            return f"O processador está em {psutil.cpu_percent(interval=0.4):.0f} por cento, {t}."
        if re.search(r"\b(disco|armazenamento|espaco)\b", n):
            du = psutil.disk_usage("C:\\")
            return f"O disco C tem {du.free / 2**30:.0f} gigabytes livres, {du.percent:.0f} por cento em uso."
        if re.search(r"\bbateria\b", n):
            bat = psutil.sensors_battery()
            if bat is None:
                return f"Este computador não tem bateria, {t}."
            plug = "carregando" if bat.power_plugged else "na bateria"
            return f"Bateria em {bat.percent:.0f} por cento, {plug}, {t}."
        return None

    def _media(self, n: str):
        t = self.title
        steps = 5
        m = re.search(r"\b(\d{1,2})\s*(?:%|por cento|pontos|vezes)?", n)
        if m:
            steps = max(1, int(m.group(1)) // 2) if ("%" in n or "por cento" in n) else int(m.group(1))
        if re.search(r"\b(aument\w*|sob\w*|mais alto|mais volume)\b", n) and "volume" in n or n in ("mais alto",):
            return {"action": "volume_up", "steps": steps}, f"Volume aumentado, {t}."
        if re.search(r"\b(abaix\w*|diminu\w*|baix\w*|mais baixo|menos volume)\b", n) and ("volume" in n or "som" in n):
            return {"action": "volume_down", "steps": steps}, f"Volume reduzido, {t}."
        if re.search(r"^(mut\w*|silenci\w*|tir\w* o som|sem som)\b", n):
            return {"action": "mute"}, f"Som desativado, {t}."
        if re.search(r"\b(pau[sz]\w*|para a musica|pare a musica|para o video|pare o video)\b", n):
            return {"action": "play_pause"}, "Pausado."
        if re.search(r"\b(continu\w*|retom\w*|despaus\w*|da play|de play|toca a musica|volta a tocar|play)\b", n) and \
                not re.search(r"\b(abr|abre)\b", n):
            return {"action": "play_pause"}, "Retomando."
        if re.search(r"\b(proxima|pul\w*|avanc\w*)\b.*\b(musica|faixa|video)?\b", n) and \
                re.search(r"\b(musica|faixa|proxima)\b", n):
            return {"action": "next"}, "Próxima faixa."
        if re.search(r"\b(anterior|volt\w* a musica|musica anterior|faixa anterior)\b", n):
            return {"action": "previous"}, "Faixa anterior."
        return None

    async def _run(self, tool: str, args: dict, ok: str, fail: Optional[str] = None, quiet: bool = False):
        from core.plugin_system import get_tool
        spec = get_tool(tool)
        if spec is None:
            return None
        print(f"[JARVIS] Reflexo: {tool}({args})")
        self.last_call = (tool, args)
        if self.dry_run:
            return ok
        try:
            if asyncio.iscoroutinefunction(spec.function):
                result = await spec.function(**args)
            else:
                result = await asyncio.get_running_loop().run_in_executor(None, lambda: spec.function(**args))
        except Exception as e:
            result = {"success": False, "message": str(e)}
        if isinstance(result, dict) and result.get("success"):
            return ok
        if quiet:
            return None
        return fail or f"Receio que não funcionou, {self.title}: {result.get('message', 'erro desconhecido')}"
