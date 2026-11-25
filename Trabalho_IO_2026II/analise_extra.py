# -*- coding: utf-8 -*-
"""
Análise complementar do grupo (NÃO substitui os resultados oficiais de experimentos.py).

Reexecuta exatamente as configurações oficiais de X1 e X6 (mesmas cargas, parâmetros e
simuladores, sem alterar nada) e só INSTRUMENTA os objetos para medir causas que os CSVs
oficiais não mostram:

  X1: utilização do disco, tempo médio de serviço por requisição, tamanho médio da fila no
      momento da escolha e quantas vezes o SCAN foi até a borda do disco.
  X6: tamanho das rajadas da sincronização periódica (write-back), expulsões de blocos
      sujos, e resposta das leituras separada da resposta das escritas.

Saída: resultados/extras/x1_extras.csv e resultados/extras/x6_extras.csv.
Uso:   python analise_extra.py
"""
import csv
import os

from simes.disco import DiscoHDD
from simes.es.cache import criar_cache
from simes.es.escalonadores import criar_escalonador
from simes.es.simulador import simular_es
from simes.metricas import media, percentil
from experimentos import carga_es

AQUI = os.path.dirname(os.path.abspath(__file__))
SAIDA = os.path.join(AQUI, "resultados", "extras")


class EscalonadorMedido:
    """Envolve um escalonador e registra o tamanho da fila e as idas à borda."""

    def __init__(self, escalonador):
        self.interno = escalonador
        self.filas = []
        self.idas_borda = 0

    def escolher(self, fila, cabeca, direcao, agora, max_cilindro):
        self.filas.append(len(fila))
        resposta = self.interno.escolher(fila, cabeca, direcao, agora, max_cilindro)
        if resposta[2]:
            self.idas_borda += 1
        return resposta


class CacheMedida:
    """Envolve uma cache e registra rajadas de sincronização e expulsões de sujos."""

    def __init__(self, cache):
        self.interna = cache
        self.escrita = cache.escrita
        self.rajadas = []
        self.sujos_expulsos = 0

    def ler(self, bloco):
        return self.interna.ler(bloco)

    def inserir(self, bloco):
        expulsos = self.interna.inserir(bloco)
        self.sujos_expulsos += len(expulsos)
        return expulsos

    def escrever(self, bloco):
        gravar = self.interna.escrever(bloco)
        if self.escrita == "write-back":
            self.sujos_expulsos += len(gravar)
        return gravar

    def sincronizar(self):
        gravar = self.interna.sincronizar()
        self.rajadas.append(len(gravar))
        return gravar

    def sujos(self):
        return self.interna.sujos()


def ocupacao_disco(reqs, escalonador, cache=None, queda=None):
    """Fração do tempo com o disco ocupado. O custo do polling é a duração de cada
    atendimento, então cpu_es_pct no modo polling é exatamente a utilização do disco
    (o modo de CPU não afeta o escalonamento)."""
    res = simular_es(reqs, escalonador, DiscoHDD(), "polling", cache=cache, queda_ms=queda)
    return res["cpu_es_pct"] / 100.0


def gravar(nome, linhas):
    os.makedirs(SAIDA, exist_ok=True)
    with open(os.path.join(SAIDA, nome), "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(linhas[0]))
        w.writeheader()
        for l in linhas:
            w.writerow({k: ("%.4f" % v if isinstance(v, float) else v) for k, v in l.items()})
    print("gravado: resultados/extras/%s (%d linhas)" % (nome, len(linhas)))


def x1_extras():
    linhas = []
    for carga in ("sequencial", "aleatoria", "concentrada", "rajadas"):
        reqs = carga_es(carga)
        for nome in ("FCFS", "SSTF", "SCAN"):
            esc = EscalonadorMedido(criar_escalonador(nome))
            res = simular_es(reqs, esc, DiscoHDD(), "interrupcao")
            servicos = [r.fim - r.inicio for r in res["concluidas"]]
            linhas.append({
                "carga": carga, "escalonador": nome,
                "utilizacao_disco": ocupacao_disco(reqs, criar_escalonador(nome)),
                "servico_medio_ms": media(servicos),
                "deslocamento_por_req": res["deslocamento_total"] / float(res["requisicoes"]),
                "fila_media_na_escolha": media(esc.filas),
                "idas_a_borda": esc.idas_borda,
            })
    gravar("x1_extras.csv", linhas)


def x6_extras():
    reqs = carga_es("reuso")
    queda = reqs[len(reqs) // 2].chegada
    linhas = []
    configs = [("nenhuma", "", "")] + [(n, c, e) for n in ("LRU", "FIFO")
                                         for c in (64, 128, 256, 512, 1024, 2048)
                                         for e in ("write-through", "write-back")]
    for nome, cap, escrita in configs:
        cache = CacheMedida(criar_cache(nome, cap, escrita)) if nome != "nenhuma" else None
        res = simular_es(reqs, criar_escalonador("FCFS"), DiscoHDD(), "interrupcao", cache=cache, queda_ms=queda)
        leituras = [r for r in res["concluidas"] if r.tipo == "L"]
        escritas = [r for r in res["concluidas"] if r.tipo == "E"]
        cache2 = criar_cache(nome, cap, escrita) if nome != "nenhuma" else None
        linhas.append({
            "cache": nome, "capacidade_cache": cap, "escrita": escrita,
            "utilizacao_disco": ocupacao_disco(reqs, criar_escalonador("FCFS"), cache2, queda),
            "resposta_media_leituras_ms": media(r.resposta for r in leituras),
            "resposta_p95_leituras_ms": percentil([r.resposta for r in leituras], 95),
            "espera_max_leituras_ms": max(r.espera for r in leituras),
            "resposta_media_escritas_ms": media(r.resposta for r in escritas),
            "sincronizacoes": len(cache.rajadas) if cache else 0,
            "rajada_media_blocos": media(cache.rajadas) if cache else 0.0,
            "rajada_max_blocos": max(cache.rajadas, default=0) if cache else 0,
            "sujos_expulsos": cache.sujos_expulsos if cache else 0,
        })
    gravar("x6_extras.csv", linhas)


if __name__ == "__main__":
    x1_extras()
    x6_extras()
