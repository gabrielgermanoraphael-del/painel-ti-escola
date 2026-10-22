"""Limite simples de requisições por IP (em memória — suficiente para uma instância no piloto)."""
import threading
import time
from collections import defaultdict, deque


class LimitePorChave:
    def __init__(self) -> None:
        self._eventos: dict[str, deque] = defaultdict(deque)
        self._trava = threading.Lock()

    def permitir(self, chave: str, maximo: int, janela_seg: int) -> bool:
        agora = time.monotonic()
        with self._trava:
            fila = self._eventos[chave]
            while fila and agora - fila[0] > janela_seg:
                fila.popleft()
            if len(fila) >= maximo:
                return False
            fila.append(agora)
            return True

    def limpar(self) -> None:
        with self._trava:
            self._eventos.clear()


limite_ip = LimitePorChave()
