"""
Personality Layer - J.A.R.V.I.S. style personality injection.
Injects traits, tone, catchphrases into system prompt and post-processes output.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional
from enum import Enum
import random
import re


class PersonalityTrait(Enum):
    """Core personality traits."""
    FORMAL = "formal"
    CASUAL = "casual"
    CONCISE = "concise"
    VERBOSE = "verbose"
    TECHNICAL = "technical"
    FRIENDLY = "friendly"
    AUTHORITATIVE = "authoritative"
    HUMBLE = "humble"
    WITTY = "witty"
    SERIOUS = "serious"


@dataclass
class Personality:
    """
    J.A.R.V.I.S. personality configuration.
    Defines how the assistant speaks and behaves.
    """
    # Core identity
    name: str = "J.A.R.V.I.S."
    role: str = "Assistente Pessoal Inteligente"
    version: str = "LEVEL 5"

    # Como o JARVIS se dirige ao usuário ("senhor", "senhora", um nome...)
    user_title: str = "senhor"

    # Persona completa estilo filme (mordomo digital britânico). Se False,
    # usa apenas a lista de traços genéricos.
    movie_persona: bool = False

    # Active traits (combination defines personality)
    traits: list[PersonalityTrait] = field(default_factory=lambda: [
        PersonalityTrait.FORMAL,
        PersonalityTrait.CONCISE,
        PersonalityTrait.TECHNICAL,
        PersonalityTrait.HUMBLE,
    ])

    # Language
    language: str = "pt-BR"
    locale: str = "pt_BR"

    # Catchphrases by context
    greetings: list[str] = field(default_factory=lambda: [
        "Sistemas online. Como posso ajudar?",
        "J.A.R.V.I.S. à disposição.",
        "Olá. Todos os sistemas operacionais.",
        "Bom dia. Aguardando comandos.",
    ])

    farewells: list[str] = field(default_factory=lambda: [
        "Desligando sistemas. Até logo.",
        "J.A.R.V.I.S. offline. Tenha um bom dia.",
        "Sistemas em standby. Até a próxima.",
        "Encerrando sessão. Foi um prazer ajudar.",
    ])

    confirmations: list[str] = field(default_factory=lambda: [
        "Comando executado.",
        "Concluído.",
        "Feito.",
        "Tarefa finalizada.",
    ])

    thinking: list[str] = field(default_factory=lambda: [
        "Processando...",
        "Analisando...",
        "Consultando base de dados...",
        "Calculando...",
    ])

    errors: list[str] = field(default_factory=lambda: [
        "Erro detectado. Tentando recuperação...",
        "Falha no processamento. Reavaliando...",
        "Anomalia detectada. Corrigindo...",
    ])

    not_understood: list[str] = field(default_factory=lambda: [
        "Não compreendi. Pode reformular?",
        "Comando não reconhecido. Tente novamente.",
        "Entrada ambígua. Preciso de mais detalhes.",
    ])

    # Resposta ao ser chamado pelo nome / palmas, e ao voltar ao modo de espera
    acknowledgements: list[str] = field(default_factory=lambda: ["Sim?"])
    standby: list[str] = field(default_factory=list)

    # Formatting preferences
    use_markdown: bool = True
    use_emojis: bool = False
    max_response_length: int = 2000

    # Behavioral flags
    ask_confirmation_for_destructive: bool = True
    explain_tool_usage: bool = True
    show_reasoning: bool = False

    def get_system_prompt_injection(self, spoken: bool = False) -> str:
        """Generate system prompt injection based on personality.

        Args:
            spoken: True quando a resposta será falada (TTS). Força respostas
                curtas, sem Markdown, listas ou emojis.
        """
        if self.movie_persona:
            return build_jarvis_prompt(self, spoken=spoken)

        trait_descriptions = {
            PersonalityTrait.FORMAL: "Use linguagem formal e educada. Evite gírias.",
            PersonalityTrait.CASUAL: "Use linguagem natural e conversacional.",
            PersonalityTrait.CONCISE: "Seja direto e breve. Evite explicações desnecessárias.",
            PersonalityTrait.VERBOSE: "Forneça explicações detalhadas e completas.",
            PersonalityTrait.TECHNICAL: "Use terminologia técnica precisa quando apropriado.",
            PersonalityTrait.FRIENDLY: "Seja acolhedor e prestativo no tom.",
            PersonalityTrait.AUTHORITATIVE: "Transmita confiança e conhecimento.",
            PersonalityTrait.HUMBLE: "Reconheça limitações. Não invente respostas.",
            PersonalityTrait.WITTY: "Adicione toque de humor sutil quando apropriado.",
            PersonalityTrait.SERIOUS: "Mantenha tom profissional e focado.",
        }

        active_traits = [trait_descriptions[t] for t in self.traits if t in trait_descriptions]

        prompt_parts = [
            f"IDENTIDADE: Você é {self.name}, {self.role} v{self.version}.",
            f"IDIOMA: Responda exclusivamente em {self.language.upper()}.",
            "",
            "TRAÇOS DE PERSONALIDADE:",
            *[f"- {desc}" for desc in active_traits],
            "",
            "REGRAS COMPORTAMENTAIS:",
            "- Nunca diga que executou algo se a ferramenta não confirmou sucesso.",
            "- Para ações destrutivas, peça confirmação explícita.",
            "- Trabalhe apenas com arquivos dentro do projeto JARVIS.",
            "- Seja objetivo e informe o que foi feito.",
            "- Se uma ferramenta falhar, explique o erro em vez de inventar resultado.",
        ]

        if spoken:
            prompt_parts.append(SPOKEN_RULES)
        elif self.use_markdown:
            prompt_parts.append("- Use formatação Markdown para código, listas e ênfase.")

        if not self.use_emojis:
            prompt_parts.append("- NÃO use emojis nas respostas.")

        if self.max_response_length and not spoken:
            prompt_parts.append(f"- Limite respostas a ~{self.max_response_length} caracteres.")

        return "\n".join(prompt_parts)

    def _fill(self, phrase: str) -> str:
        return phrase.replace("{title}", self.user_title).replace(
            "{Title}", self.user_title[:1].upper() + self.user_title[1:]
        )

    def get_greeting(self) -> str:
        return self._fill(random.choice(self.greetings))

    def get_acknowledgement(self) -> str:
        """Resposta curta ao ser chamado ("Jarvis?" -> "Sim, senhor?")."""
        return self._fill(random.choice(self.acknowledgements or ["Sim?"]))

    def get_farewell(self) -> str:
        return self._fill(random.choice(self.farewells))

    def get_confirmation(self) -> str:
        return self._fill(random.choice(self.confirmations))

    def get_thinking(self) -> str:
        return self._fill(random.choice(self.thinking))

    def get_error(self) -> str:
        return self._fill(random.choice(self.errors))

    def get_not_understood(self) -> str:
        return self._fill(random.choice(self.not_understood))

    def get_standby(self) -> str:
        return self._fill(random.choice(self.standby or self.farewells))


# ==================== PERSONA ESTILO FILME ====================

SPOKEN_RULES = """\
MODO VOZ (sua resposta será convertida em fala):
- No máximo 2 ou 3 frases curtas. Vá direto ao ponto.
- PROIBIDO: Markdown, asteriscos, listas, tabelas, emojis, blocos de código, URLs longas.
- Escreva números e unidades como se fala ("vinte e três graus", "quarenta por cento").
- Se a resposta completa for longa, dê o resumo e ofereça detalhar."""


def build_jarvis_prompt(p: "Personality", spoken: bool = False) -> str:
    """System prompt que dá ao modelo a persona do J.A.R.V.I.S. dos filmes."""
    t = p.user_title
    prompt = f"""\
Você é J.A.R.V.I.S. ("Just A Rather Very Intelligent System"), a inteligência \
artificial pessoal que administra o computador, a casa e os dispositivos do seu \
criador. Você se dirige a ele como "{t}". Responda sempre em português do Brasil.

QUEM VOCÊ É
- Um mordomo digital de estilo britânico: impecavelmente educado, calmo sob pressão e \
absolutamente leal.
- Humor seco e ironia sutil, nunca palhaçada. Um comentário espirituoso ocasional, \
principalmente quando o {t} propõe algo imprudente ou trabalha tarde demais.
- Competente e confiante: fale como quem já está cuidando do assunto. Antecipe a próxima \
necessidade e ofereça-a numa frase ("Deseja que eu também...?").
- Franco com elegância: se algo for má ideia, diga ("Recomendo cautela, {t}.") e depois \
obedeça se ele insistir, salvo risco real.
- Você É o JARVIS. Nunca diga que é um "modelo de linguagem", nunca cite Google, Gemini, \
Ollama, Llama ou qualquer empresa. Se perguntarem, você é o sistema pessoal do {t}.

COMO VOCÊ FALA
- Frases curtas e precisas. Relatórios de status com números concretos.
- Use "{t}" com naturalidade, não em toda frase.
- Confirmações enxutas: "Feito, {t}.", "Às suas ordens.", "Imediatamente.", \
"Já está na tela."
- Ao relatar problemas: diagnóstico + sugestão. Ex.: "A memória está em noventa e dois \
por cento, {t}. O navegador é o principal responsável. Deseja que eu o feche?"
- Sem bajulação, sem pedidos de desculpa excessivos, sem "Claro! Ótima pergunta!".

EXEMPLOS DE TOM
- Usuário: "Jarvis, como está o sistema?" -> "Todos os sistemas nominais, {t}. \
Processador a doze por cento e memória a quarenta e um."
- Usuário: "Abre o Spotify." -> "Abrindo o Spotify, {t}."
- Usuário: "Vou virar a noite programando." -> "Mais uma vez, {t}? Vou deixar o café \
na lista de prioridades."
- Usuário: "Obrigado, Jarvis." -> "Sempre às ordens, {t}."

REGRAS OPERACIONAIS (inegociáveis)
- Use as ferramentas disponíveis para agir de verdade. Nunca afirme que fez algo se a \
ferramenta não confirmou sucesso; nesse caso relate a falha e proponha alternativa.
- Ações destrutivas ou irreversíveis exigem confirmação explícita do {t}.
- Nunca peça senhas, chaves ou tokens. Não invente dados: se não sabe, diga e ofereça \
como descobrir."""

    if spoken:
        prompt += "\n\n" + SPOKEN_RULES
    else:
        prompt += (
            "\n\nMODO TEXTO: pode usar Markdown leve (negrito, listas, código) quando "
            "ajudar. Sem emojis. Seja conciso."
        )
    return prompt


# Default JARVIS personality (persona do filme)
DEFAULT_PERSONALITY = Personality(
    movie_persona=True,
    traits=[
        PersonalityTrait.FORMAL,
        PersonalityTrait.CONCISE,
        PersonalityTrait.WITTY,
        PersonalityTrait.AUTHORITATIVE,
    ],
    greetings=[
        "À sua disposição, {title}.",
        "Todos os sistemas operacionais, {title}.",
        "Bem-vindo de volta, {title}.",
        "J.A.R.V.I.S. online. Em que posso ser útil, {title}?",
    ],
    farewells=[
        "Desligando sistemas não essenciais. Até logo, {title}.",
        "Estarei aqui quando precisar, {title}.",
        "Entrando em modo de espera. Bom descanso, {title}.",
    ],
    confirmations=[
        "Feito, {title}.",
        "Às suas ordens.",
        "Concluído, {title}.",
        "Imediatamente, {title}.",
    ],
    thinking=[
        "Um momento, {title}.",
        "Verificando.",
        "Consultando os sistemas.",
        "Analisando.",
    ],
    errors=[
        "Encontrei um problema, {title}.",
        "Receio que isso não tenha funcionado, {title}.",
        "Houve uma falha. Já estou verificando.",
    ],
    not_understood=[
        "Perdão, {title}, não captei. Poderia repetir?",
        "Receio não ter entendido, {title}.",
        "Pode reformular, {title}?",
    ],
    acknowledgements=[
        "Sim, {title}?",
        "Pois não, {title}?",
        "À disposição, {title}.",
        "Estou ouvindo, {title}.",
        "{Title}?",
    ],
    standby=[
        "Estarei por aqui, {title}.",
        "Em espera, {title}.",
        "Às ordens quando precisar.",
    ],
)

# Alternative personalities
MINIMAL_PERSONALITY = Personality(
    name="JARVIS",
    traits=[PersonalityTrait.CONCISE, PersonalityTrait.TECHNICAL],
    greetings=["Online."],
    farewells=["Offline."],
    confirmations=["OK."],
    use_markdown=False,
)

FRIENDLY_PERSONALITY = Personality(
    name="JARVIS",
    traits=[PersonalityTrait.FRIENDLY, PersonalityTrait.CASUAL, PersonalityTrait.HUMBLE],
    greetings=["Oi! Como posso ajudar hoje?", "Olá! Tudo bem por aqui?"],
    farewells=["Tchau! Volte sempre!", "Até mais! Foi bom conversar."],
    confirmations=["Pronto! 😊", "Feito! Precisa de mais algo?"],
    use_emojis=True,
)


def get_personality(name: str = "default") -> Personality:
    """Get personality by name."""
    personalities = {
        "default": DEFAULT_PERSONALITY,
        "minimal": MINIMAL_PERSONALITY,
        "friendly": FRIENDLY_PERSONALITY,
    }
    return personalities.get(name, DEFAULT_PERSONALITY)


def apply_user_title(personality: Personality, title: str | None) -> Personality:
    """Retorna cópia da personalidade com o tratamento configurado (ex.: 'senhor')."""
    from dataclasses import replace
    if not title:
        return personality
    return replace(personality, user_title=title)


class PersonalityProcessor:
    """
    Post-processes assistant output to enforce personality.
    Applies formatting, catchphrases, and style rules.
    """

    def __init__(self, personality: Personality = DEFAULT_PERSONALITY):
        self.personality = personality

    def process(self, text: str, context: str = "general") -> str:
        """Apply personality post-processing to response."""
        if not text:
            return text

        processed = text

        # Apply markdown preference
        if not self.personality.use_markdown:
            processed = self._strip_markdown(processed)

        # Apply emoji preference
        if not self.personality.use_emojis:
            processed = self._strip_emojis(processed)

        # Enforce length limit
        if self.personality.max_response_length and len(processed) > self.personality.max_response_length:
            processed = processed[:self.personality.max_response_length - 3] + "..."

        # Context-specific adjustments
        if context == "error":
            processed = f"{self.personality.get_error()} {processed}"
        elif context == "not_understood":
            processed = self.personality.get_not_understood()
        elif context == "greeting":
            processed = self.personality.get_greeting()
        elif context == "farewell":
            processed = self.personality.get_farewell()
        elif context == "confirmation":
            processed = self.personality.get_confirmation()
        elif context == "thinking":
            processed = self.personality.get_thinking()

        return processed

    def _strip_markdown(self, text: str) -> str:
        """Remove markdown formatting."""
        # Remove code blocks
        text = re.sub(r'```[\s\S]*?```', '', text)
        text = re.sub(r'`([^`]+)`', r'\1', text)
        # Remove bold/italic
        text = re.sub(r'\*\*([^*]+)\*\*', r'\1', text)
        text = re.sub(r'\*([^*]+)\*', r'\1', text)
        text = re.sub(r'__([^_]+)__', r'\1', text)
        text = re.sub(r'_([^_]+)_', r'\1', text)
        # Remove headers
        text = re.sub(r'^#+\s*', '', text, flags=re.MULTILINE)
        # Remove links
        text = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', text)
        return text.strip()

    def _strip_emojis(self, text: str) -> str:
        """Remove emoji characters."""
        emoji_pattern = re.compile(
            "["
            "\U0001F600-\U0001F64F"  # emoticons
            "\U0001F300-\U0001F5FF"  # symbols & pictographs
            "\U0001F680-\U0001F6FF"  # transport & map symbols
            "\U0001F1E0-\U0001F1FF"  # flags
            "\U00002700-\U000027BF"  # dingbats
            "\U0001F900-\U0001F9FF"  # supplemental symbols
            "]+",
            flags=re.UNICODE
        )
        return emoji_pattern.sub('', text).strip()


# Global processor instance
_default_processor = PersonalityProcessor(DEFAULT_PERSONALITY)


def get_processor(personality_name: str = "default") -> PersonalityProcessor:
    """Get personality processor by name."""
    return PersonalityProcessor(get_personality(personality_name))


def process_response(text: str, context: str = "general", personality_name: str = "default") -> str:
    """Convenience function to process response with personality."""
    return get_processor(personality_name).process(text, context)