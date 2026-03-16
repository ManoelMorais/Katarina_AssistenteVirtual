from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

MAX_CONTEXT_CHARS = 1500


@dataclass
class ScreenContext:
    current_text: str = ""
    current_window: str = ""
    last_update: Optional[datetime] = None
    history: list = field(default_factory=list)

    def to_prompt_snippet(self) -> str:
        """Bloco injetado silenciosamente no system prompt da Katarina."""
        if not self.current_text:
            return ""
        ts = self.last_update.strftime("%H:%M:%S") if self.last_update else "?"
        return (
            f"[CONTEXTO DE TELA — {ts}]\n"
            f"Janela ativa: {self.current_window}\n"
            f"Conteúdo visível:\n{self.current_text[:MAX_CONTEXT_CHARS]}\n"
            f"[FIM DO CONTEXTO DE TELA]"
        )

    def has_content(self) -> bool:
        return bool(self.current_text.strip())

screen_ctx = ScreenContext()
