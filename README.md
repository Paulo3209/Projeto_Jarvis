# J.A.R.V.I.S. — Assistente pessoal para Windows

Assistente por voz inspirado no JARVIS dos filmes: mordomo digital educado, com humor seco,
que conversa por voz, aparece numa interface holográfica ao ser chamado e controla o PC,
o celular e os aparelhos da rede.

## Como usar

```powershell
python main.py --voice        # Modo voz + interface holográfica (recomendado)
python main.py                # Modo texto no terminal (com ferramentas)
python main.py --gui          # HUD completa em PyQt6
python -m gui.jarvis_overlay --demo   # Ver só a interface holográfica
```

**Modo voz**
1. Diga **"Jarvis"** ou bata **2 palmas**. A interface aparece e ele responde "Sim, senhor?".
2. Dê o comando: *"abra o Spotify"*, *"como está o sistema?"*, *"apague a luz da sala"*.
3. Durante alguns segundos (`conversation_window`) ele continua ouvindo sem precisar repetir o nome.
4. *"Obrigado"* / *"isso é tudo"* → modo espera. *"Desligue-se"* → encerra.

Respostas instantâneas (sem IA): horas, data, status do sistema.

## Segurança: confirmação por voz

Com `control_mode: "full"` o JARVIS pode executar PowerShell, encerrar processos, desligar o PC,
mexer em arquivos e mandar comandos ao celular e a outros aparelhos. **Toda ação sensível pede
autorização** ("Isso requer sua autorização, senhor... Confirma?") e só roda se você disser
"sim"/"confirmo". Use `control_mode: "safe"` para permitir apenas ações inofensivas.

## Configuração (`config.yaml`)

| Chave | Padrão | Função |
|---|---|---|
| `user_title` | `senhor` | Como ele te chama |
| `llm_primary` | `ollama` | Motor principal (`ollama` local ou `gemini`); o outro é fallback automático |
| `ollama_model` | `llama3.1:8b` | Precisa suportar *tools* para executar ações |
| `edge_voice` | `pt-BR-AntonioNeural` | Voz masculina grave |
| `stt_model` | `small` | Reconhecimento de fala (o 1º uso baixa o modelo) |
| `conversation_window` | `8.0` | Segundos ouvindo follow-ups |
| `control_mode` | `full` | `full` (PC + celular + rede, com confirmação) ou `safe` |

Segredos ficam no `.env` (ex.: `GEMINI_API_KEY=...`), que não é versionado.

## Controlar o celular (Android) pela rede Wi-Fi

O JARVIS usa ADB. Ele só controla aparelhos que **você** autorizou:

1. No celular: *Opções do desenvolvedor → Depuração por Wi-Fi* → **Parear com código**.
2. No PC (com [platform-tools](https://developer.android.com/tools/releases/platform-tools) no PATH):
   ```powershell
   adb pair IP:PORTA_DE_PAREAMENTO   # digite o código mostrado no celular
   adb connect IP:PORTA
   ```
3. Diga: *"Jarvis, qual a bateria do celular?"*, *"abra o WhatsApp no celular"*.

## Outros aparelhos da rede

- *"Jarvis, quais dispositivos estão na rede?"* — varredura da rede local.
- Computadores/servidores/Raspberry Pi: via SSH (configure as credenciais no cofre de
  credenciais do projeto).
- Luzes, TV, ar-condicionado, tomadas: via Home Assistant — registre sua instância como
  dispositivo (ferramenta `register_device`, protocolo `home_assistant`) e o JARVIS passa a
  controlá-la pelas ferramentas `hass_*`.

## Arquitetura (principais módulos)

- `core/personality.py` — persona J.A.R.V.I.S. (prompt, frases, modo voz)
- `core/jarvis_agent.py` — motor de IA (Ollama/Gemini) + ferramentas + confirmação
- `core/brain.py` — integração Gemini com loop de ferramentas
- `voice/assistant.py` — loop de conversa por voz (wake word, janela de conversa, palmas)
- `voice/stt.py`, `voice/tts_hybrid.py` — reconhecimento e síntese de fala
- `gui/jarvis_overlay.py` — interface holográfica animada
- `tools/` — ~190 ferramentas (PC, Android, rede, visão, casa inteligente)
