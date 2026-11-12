# JARVIS Auto-Start Setup

Este guia explica como configurar o JARVIS para:
1. **Iniciar automaticamente** quando você ligar o PC / fizer login no Windows
2. **Dar "bom dia", "boa tarde" ou "boa noite"** baseado no horário
3. **Desbloquear o PC** com o comando de voz "jarvis desbloquear PC"

---

## 📋 Pré-requisitos

- Windows 10/11
- Python 3.10+ com ambiente virtual configurado (`.venv`)
- JARVIS funcionando em modo de voz (`python main.py --voice`)

---

## 🚀 Configuração Rápida (Recomendada)

### 1. Abra PowerShell como Administrador
- Pressione `Win + X` → **Terminal (Admin)** ou **Windows PowerShell (Admin)**

### 2. Execute o script de configuração
```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
cd C:\Users\paulo\jarvis\automation
.\setup_autostart.ps1
```

### 3. Reinicie o PC para testar
O JARVIS iniciará automaticamente na próxima vez que você fizer login.

---

## 🔧 Configuração Manual (Alternativa)

Se preferir configurar manualmente via **Agendador de Tarefas**:

1. Abra **Agendador de Tarefas** (`taskschd.msc`)
2. **Criar Tarefa...** (lado direito)
3. **Geral:**
   - Nome: `JARVIS Auto-Start`
   - ✅ Executar com privilégios mais altos
   - Configurar para: Windows 10/11
4. **Triggers:**
   - Novo → **No logon** → Qualquer usuário
5. **Ações:**
   - Nova → Iniciar programa
   - Programa: `wscript.exe`
   - Argumentos: `"C:\Users\paulo\jarvis\automation\start_jarvis_silent.vbs"`
   - Iniciar em: `C:\Users\paulo\jarvis`
6. **Condições:**
   - ❌ Iniciar a tarefa somente se a rede estiver disponível (opcional)
7. **Configurações:**
   - ✅ Permitir execução sob demanda
   - ✅ Executar a tarefa o mais rápido possível se agendamento perdido
   - ✅ Se a tarefa falhar, reiniciar a cada: 1 minuto (tentar 3 vezes)

---

## 🎤 Como Usar

### Inicialização Automática
Ao fazer login no Windows, o JARVIS iniciará em modo de voz e dirá algo como:
- *"Bom dia, Senhor. Tenha uma excelente manhã."* (5h-12h)
- *"Boa tarde, Senhor. Como posso ajudar nesta tarde?"* (12h-18h)
- *"Boa noite, Senhor. Trabalhando tarde hoje?"* (18h-5h)

### Comando de Desbloqueio
Com o JARVIS rodando (ouvindo "jarvis"):
> **Você:** "jarvis desbloquear PC"
> **JARVIS:** Executa o comando de desbloqueio

> ⚠️ **Importante:** O Windows **não permite** desbloquear a sessão programaticamente sem credenciais por segurança. O comando:
> - Acorda o monitor (se estiver desligado)
> - Envia `Ctrl+Alt+Del` para trazer a tela de login
> - **Você ainda precisará digitar senha/PIN/Windows Hello**

### Outros Comandos de Voz Úteis
- "jarvis que horas são" → Hora atual
- "jarvis abrir bloco de notas" → Abre Notepad
- "jarvis abrir calculadora" → Abre Calculadora
- "jarvis informações do sistema" → Info do PC

---

## 🛠️ Solução de Problemas

### JARVIS não inicia no boot
1. Verifique o **Visualizador de Eventos** → Windows Logs → Application
2. Procure por eventos do "Task Scheduler"
3. Execute manualmente para testar:
   ```cmd
   wscript.exe "C:\Users\paulo\jarvis\automation\start_jarvis_silent.vbs"
   ```

### Erro de permissão no PowerShell
```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

### Ambiente virtual não encontrado
Edite `start_jarvis_silent.vbs` e ajuste o caminho do Python:
```vbscript
pythonPath = "C:\caminho\para\python.exe"
```

### Microfone não funciona no boot
- Verifique se o microfone tem permissão para apps desktop
- Configurações → Privacidade → Microfone → "Permitir que apps acessem seu microfone"

---

## 📁 Arquivos Envolvidos

| Arquivo | Descrição |
|---------|-----------|
| `automation/start_jarvis_silent.vbs` | Launcher silencioso (sem janela do console) |
| `automation/setup_autostart.ps1` | Script PowerShell para criar tarefa agendada |
| `tools/startup.py` | Ferramentas: saudação por horário, desbloqueio PC |
| `main.py` | Ponto de entrada - fala saudação ao iniciar modo voz |

---

## 🔄 Desativar Auto-Start

### Via PowerShell (Admin):
```powershell
Unregister-ScheduledTask -TaskName "JARVIS Auto-Start" -Confirm:$false
```

### Via Agendador de Tarefas:
1. Abra `taskschd.msc`
2. Biblioteca do Agendador de Tarefas → JARVIS Auto-Start
3. Botão direito → **Excluir**

---

## 📝 Personalização

### Mudar nome do usuário na saudação
Edite `main.py` na função `run_voice_mode`:
```python
greeting_result = get_startup_greeting("SeuNome")  # Mude "Senhor" para seu nome
```

### Mudar horários das saudações
Edite `tools/startup.py` na função `get_startup_greeting`:
```python
if 5 <= hour < 12:      # Bom dia: 5h-12h
elif 12 <= hour < 18:   # Boa tarde: 12h-18h
else:                   # Boa noite: 18h-5h
```

### Desativar saudação por voz
Em `main.py`, comente ou remova:
```python
# await voice_bridge.speak(greeting_text, blocking=True)
```

---

## 🆘 Suporte

Se tiver problemas:
1. Verifique os logs no console (execute `python main.py --voice` manualmente)
2. Confira se o `.venv` está ativo e dependências instaladas (`pip install -r requirements.txt`)
3. Teste o microfone: `python -m voice.stt`
4. Teste o TTS: `python -m voice.tts`