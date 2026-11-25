# -*- coding: utf-8 -*-
"""
Módulo M1 — cache de blocos (buffer cache).

Referência: Silberschatz, 9ª ed., 13.4.3 (Caching) e 12.6 (Efficiency and Performance) — pesquisa.

Implementem CacheLRU e CacheFIFO com a interface abaixo. O simulador de E/S chama:

    ler(bloco) -> bool
        True se o bloco está na cache (acerto). Num acerto, a LRU atualiza a recência;
        a FIFO não muda nada.
    inserir(bloco) -> list[int]
        Chamado depois de uma falta de leitura, quando o bloco chega do disco. Se a cache
        estiver cheia, expulsa uma vítima (LRU: a usada há mais tempo; FIFO: a que entrou
        primeiro). Devolve os blocos SUJOS expulsos, que o simulador vai gravar no disco.
    escrever(bloco) -> list[int]
        Escrita do usuário. Coloca (ou atualiza) o bloco na cache e devolve a lista de blocos
        que precisam ser gravados no disco AGORA:
          write-through: o próprio bloco (+ sujos expulsos, que não existem nesta política);
          write-back:    só os blocos sujos expulsos; o bloco escrito fica marcado como sujo.
        Uma escrita conta como acesso para a LRU.
    sincronizar() -> list[int]
        Gravação periódica (a cada INTERVALO_SYNC_MS): devolve todos os blocos sujos e os
        marca como limpos.
    sujos() -> int
        Quantos blocos estão sujos agora (usado para medir a perda numa queda de energia).

Política de escrita: 'write-through' ou 'write-back'.
"""
from collections import OrderedDict


class Cache:
    nome = "?"

    def __init__(self, capacidade, escrita="write-back"):
        if escrita not in ("write-through", "write-back"):
            raise ValueError("escrita deve ser 'write-through' ou 'write-back'")
        self.capacidade = capacidade
        self.escrita = escrita

    def ler(self, bloco):
        raise NotImplementedError

    def inserir(self, bloco):
        raise NotImplementedError

    def escrever(self, bloco):
        raise NotImplementedError

    def sincronizar(self):
        raise NotImplementedError

    def sujos(self):
        raise NotImplementedError


class _CacheOrdenada(Cache):
    """
    Base comum da LRU e da FIFO. Os blocos ficam num OrderedDict (bloco -> sujo), em ordem
    de expulsão: o primeiro item é a próxima vítima. As duas políticas só diferem em
    _usado(), chamado a cada acesso a um bloco que já está na cache.

    Escrita com alocação (write-allocate) nas duas políticas: o bloco escrito entra na cache.
    """

    def __init__(self, capacidade, escrita="write-back"):
        super().__init__(capacidade, escrita)
        if capacidade < 1:
            raise ValueError("a capacidade deve ser de pelo menos 1 bloco")
        self._blocos = OrderedDict()
        self._n_sujos = 0

    def _usado(self, bloco):
        """Atualiza a ordem de expulsão num acerto (a LRU sobrescreve)."""

    def _colocar(self, bloco, sujo):
        """Coloca (ou atualiza) o bloco; devolve os blocos sujos expulsos para abrir espaço."""
        if bloco in self._blocos:
            if sujo and not self._blocos[bloco]:
                self._blocos[bloco] = True
                self._n_sujos += 1
            self._usado(bloco)
            return []
        expulsos = []
        while len(self._blocos) >= self.capacidade:
            vitima, vitima_suja = self._blocos.popitem(last=False)
            if vitima_suja:
                self._n_sujos -= 1
                expulsos.append(vitima)
        self._blocos[bloco] = sujo
        if sujo:
            self._n_sujos += 1
        return expulsos

    def ler(self, bloco):
        if bloco in self._blocos:
            self._usado(bloco)
            return True
        return False

    def inserir(self, bloco):
        # Se o bloco já estiver na cache (uma escrita chegou enquanto a leitura esperava o
        # disco), a versão da cache é a mais nova: mantém o estado "sujo" dela.
        return self._colocar(bloco, False)

    def escrever(self, bloco):
        if self.escrita == "write-through":
            # o bloco fica limpo na cache e vai ao disco agora; nunca há sujos para expulsar
            return self._colocar(bloco, False) + [bloco]
        return self._colocar(bloco, True)

    def sincronizar(self):
        gravar = [b for b, sujo in self._blocos.items() if sujo]
        for b in gravar:
            self._blocos[b] = False
        self._n_sujos = 0
        return gravar

    def sujos(self):
        return self._n_sujos


class CacheLRU(_CacheOrdenada):
    """Least Recently Used: expulsa o bloco acessado (lido ou escrito) há mais tempo."""
    nome = "LRU"

    def _usado(self, bloco):
        self._blocos.move_to_end(bloco)


class CacheFIFO(_CacheOrdenada):
    """First-In, First-Out: expulsa o bloco que entrou primeiro; acertos não mudam a ordem."""
    nome = "FIFO"


CACHES = {"LRU": CacheLRU, "FIFO": CacheFIFO}


def criar_cache(nome, capacidade, escrita):
    try:
        return CACHES[nome](capacidade, escrita)
    except KeyError:
        raise ValueError("cache desconhecida: %s" % nome)
