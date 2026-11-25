# -*- coding: utf-8 -*-
"""Testes extras do grupo: casos-limite do núcleo (N2, N3) e do módulo M1 (cache)."""
import unittest

from simes import parametros as P
from simes.disco import DiscoHDD
from simes.es.cache import CacheFIFO, CacheLRU
from simes.es.cpu import custo_cpu
from simes.es.escalonadores import FCFS, SCAN, SSTF, percorrer
from simes.es.requisicao import Requisicao
from simes.es.simulador import simular_es
from simes.arquivos.estruturas import ErroSA
from simes.arquivos.simulador import montar_sistema


def req(i, cilindro, chegada=0.0, tipo="L", n=1, deslocamento=0):
    return Requisicao(i, chegada, "P1", tipo, cilindro * P.BLOCOS_POR_CILINDRO + deslocamento, n)


class TesteEscalonadoresExtras(unittest.TestCase):
    def test_sstf_empate_vence_quem_chegou_antes(self):
        self.assertEqual(SSTF().escolher([req(0, 60), req(1, 40)], 50, -1, 0.0, 199), (0, +1, []))
        self.assertEqual(SSTF().escolher([req(0, 40), req(1, 60)], 50, +1, 0.0, 199), (0, -1, []))

    def test_sstf_mesmo_cilindro_mantem_direcao(self):
        self.assertEqual(SSTF().escolher([req(0, 90), req(1, 50)], 50, -1, 0.0, 199), (1, -1, []))

    def test_scan_mesmo_cilindro_conta_como_a_frente(self):
        for direcao in (+1, -1):
            self.assertEqual(SCAN().escolher([req(0, 10), req(1, 50)], 50, direcao, 0.0, 199),
                             (1, direcao, []))

    def test_scan_inverte_na_borda(self):
        # nada abaixo de 50: desce até 0, inverte e atende 60
        self.assertEqual(SCAN().escolher([req(0, 60)], 50, -1, 0.0, 199), (0, +1, [0]))
        # já está na borda: não há o que percorrer
        self.assertEqual(SCAN().escolher([req(0, 60)], 0, -1, 0.0, 199), (0, +1, []))
        self.assertEqual(SCAN().escolher([req(0, 10)], 199, +1, 0.0, 199), (0, -1, []))

    def test_fila_unitaria_e_ordem_dos_empates_no_percorrer(self):
        self.assertEqual(percorrer(SSTF(), [53], 53), ([53], 0))
        self.assertEqual(percorrer(SCAN(), [53, 53], 53), ([53, 53], 0))

    def test_simulador_conta_a_ida_a_borda(self):
        reqs = [req(0, 40), req(1, 60)]
        disco = DiscoHDD(cilindro_inicial=50)
        res = simular_es(reqs, SCAN(), disco, "interrupcao")
        # direção inicial +1: atende 60 (10), vai a 4999 (4939), volta a 40 (4959)
        self.assertEqual(res["deslocamento_total"], 10 + 4939 + 4959)

    def test_sstf_nunca_desloca_mais_que_fcfs_no_exemplo_do_livro(self):
        fila = [98, 183, 37, 122, 14, 124, 65, 67]
        self.assertLess(percorrer(SSTF(), fila, 53)[1], percorrer(FCFS(), fila, 53)[1])


class TesteCPUExtras(unittest.TestCase):
    def test_interrupcao_nao_depende_da_duracao(self):
        self.assertAlmostEqual(custo_cpu("interrupcao", 1, 0.0), custo_cpu("interrupcao", 1, 99.0))

    def test_polling_cresce_com_a_duracao(self):
        self.assertAlmostEqual(custo_cpu("polling", 1, 12.5), 12.5)

    def test_modo_desconhecido(self):
        with self.assertRaises(ValueError):
            custo_cpu("magia", 1, 1.0)


class TesteSistemaArquivosExtras(unittest.TestCase):
    def setUp(self):
        self.sa = montar_sistema("contigua", total_blocos=2000)
        self.c = self.sa.camada
        self.sa.mkdir("P1", "/d")
        self.sa.create("P1", "/d/f", 10000)

    def custo(self, funcao, *args):
        antes = (self.c.leituras, self.c.escritas)
        funcao(*args)
        return self.c.leituras - antes[0], self.c.escritas - antes[1]

    def codigo(self, funcao, *args):
        with self.assertRaises(ErroSA) as ctx:
            funcao(*args)
        return ctx.exception.codigo

    def test_raiz_sem_acessos_e_caminho_relativo(self):
        self.assertEqual(self.custo(self.sa.resolver, "/"), (0, 0))
        self.assertIs(self.sa.resolver("/"), self.sa.raiz)
        self.assertEqual(self.codigo(self.sa.resolver, "d/f"), "EINVAL")
        self.assertEqual(self.codigo(self.sa.mkdir, "P1", "/"), "EEXIST")

    def test_erros_de_caminho(self):
        self.assertEqual(self.codigo(self.sa.mkdir, "P1", "/x/y"), "ENOENT")
        self.assertEqual(self.codigo(self.sa.create, "P1", "/d/f", 1), "EEXIST")
        self.assertEqual(self.codigo(self.sa.create, "P1", "/d/g", -1), "EINVAL")
        self.assertEqual(self.codigo(self.sa.unlink, "P1", "/d/nada"), "ENOENT")
        self.assertEqual(self.codigo(self.sa.unlink, "P1", "/d"), "EISDIR")
        self.assertEqual(self.codigo(self.sa.open, "P1", "/d/f", "x", "h"), "EINVAL")

    def test_handle_repetido_no_mesmo_processo(self):
        self.sa.open("P1", "/d/f", "r", "h")
        self.assertEqual(self.codigo(self.sa.open, "P1", "/d/f", "r", "h"), "EINVAL")
        self.sa.open("P1", "/d/f", "r", "h2")                 # outro handle: nova entrada
        self.assertEqual(len(self.sa.tabelas_processo["P1"]), 2)
        self.assertEqual(self.sa.tabela_global[self.sa.resolver("/d/f").id].contador, 2)

    def test_modos(self):
        self.sa.open("P1", "/d/f", "w", "w")
        self.sa.open("P1", "/d/f", "a", "a")
        self.sa.open("P1", "/d/f", "rw", "rw")
        self.assertEqual(self.codigo(self.sa.read, "P1", "w", 1), "EBADF")
        self.assertEqual(self.codigo(self.sa.read, "P1", "a", 1), "EBADF")
        self.assertEqual(self.sa.read("P1", "rw", 1), 1)
        self.assertEqual(self.sa.write("P1", "rw", 1), 1)

    def test_acrescimo_ignora_seek(self):
        self.sa.open("P1", "/d/f", "a", "h")
        self.sa.seek("P1", "h", 0)
        self.assertEqual(self.custo(self.sa.write, "P1", "h", 100), (0, 1))   # só o bloco 2
        f = self.sa.resolver("/d/f")
        self.assertEqual(f.tamanho, 10100)
        self.assertEqual(self.sa.tabelas_processo["P1"]["h"].posicao, 10100)

    def test_leitura_vazia_e_close_limpo_nao_acessam_o_disco(self):
        self.sa.open("P1", "/d/f", "r", "h")
        self.assertEqual(self.custo(self.sa.read, "P1", "h", 0), (0, 0))
        self.assertEqual(self.custo(self.sa.close, "P1", "h"), (0, 0))
        self.assertNotIn("P1", self.sa.tabelas_processo)
        self.assertEqual(self.sa.tabela_global, {})

    def test_leitura_direta_no_meio_do_arquivo(self):
        self.sa.open("P1", "/d/f", "r", "h")
        self.sa.seek("P1", "h", 4096)
        self.assertEqual(self.custo(self.sa.read, "P1", "h", 4096), (1, 0))     # só o bloco 1
        self.sa.seek("P1", "h", 4000)
        self.assertEqual(self.custo(self.sa.read, "P1", "h", 200), (2, 0))      # cruza a fronteira

    def test_escrita_alem_do_fim_estende_sem_buracos(self):
        self.sa.create("P1", "/d/vazio", 0)
        self.assertEqual(self.sa.resolver("/d/vazio").blocos, [])
        self.sa.open("P1", "/d/vazio", "w", "h")
        self.sa.seek("P1", "h", 3 * 4096)
        self.assertEqual(self.custo(self.sa.write, "P1", "h", 10), (0, 1))      # grava só o bloco 3
        g = self.sa.resolver("/d/vazio")
        self.assertEqual((g.tamanho, len(g.blocos)), (3 * 4096 + 10, 4))
        self.assertTrue(g.sujo)

    def test_unlink_de_arquivo_fechado_libera_na_hora(self):
        livres = self.sa.alocador.bitmap.livres()
        self.sa.unlink("P1", "/d/f")
        self.assertEqual(self.sa.alocador.bitmap.livres(), livres + 3)
        self.assertEqual(self.codigo(self.sa.resolver, "/d/f"), "ENOENT")

    def test_unlink_com_dois_processos_libera_so_no_ultimo_close(self):
        livres = self.sa.alocador.bitmap.livres()
        self.sa.open("P1", "/d/f", "r", "h")
        self.sa.open("P2", "/d/f", "r", "h")
        self.sa.unlink("P3", "/d/f")
        self.sa.close("P1", "h")
        self.assertEqual(self.sa.alocador.bitmap.livres(), livres)
        self.sa.close("P2", "h")
        self.assertEqual(self.sa.alocador.bitmap.livres(), livres + 3)
        # o nome pode ser reutilizado por um arquivo novo
        self.sa.create("P1", "/d/f", 1)

    def test_sem_espaco_nao_deixa_lixo(self):
        fcbs = len(self.sa.fcbs)
        self.assertEqual(self.codigo(self.sa.create, "P1", "/d/enorme", 5000 * 4096), "ENOSPC")
        self.assertEqual(len(self.sa.fcbs), fcbs)
        self.assertNotIn("enorme", self.sa.resolver("/d").entradas)


class TesteCacheExtras(unittest.TestCase):
    def test_fifo_escrita_em_bloco_presente_nao_muda_a_ordem(self):
        fifo = CacheFIFO(2, "write-back")
        fifo.inserir(1)
        fifo.inserir(2)
        fifo.escrever(1)                     # acerto de escrita: 1 continua o mais antigo
        self.assertEqual(fifo.inserir(3), [1])

    def test_lru_escrita_conta_como_acesso(self):
        lru = CacheLRU(2, "write-back")
        lru.inserir(1)
        lru.inserir(2)
        lru.escrever(1)                      # 1 vira o mais recente
        self.assertEqual(lru.inserir(3), [])  # expulsa 2, que está limpo
        self.assertTrue(lru.ler(1))
        self.assertFalse(lru.ler(2))

    def test_insercao_de_bloco_sujo_presente_nao_perde_a_escrita(self):
        lru = CacheLRU(4, "write-back")
        lru.escrever(5)
        self.assertEqual(lru.inserir(5), [])
        self.assertEqual(lru.sujos(), 1)
        self.assertEqual(lru.sincronizar(), [5])

    def test_write_through_nunca_tem_sujos(self):
        wt = CacheFIFO(2, "write-through")
        for b in range(10):
            self.assertEqual(wt.escrever(b), [b])
        self.assertEqual((wt.sujos(), wt.sincronizar()), (0, []))

    def test_capacidade_invalida(self):
        with self.assertRaises(ValueError):
            CacheLRU(0)

    def test_queda_de_energia_no_simulador(self):
        reqs = [Requisicao(i, float(i), "P1", "E", 1000 + i, 1) for i in range(5)]
        wb = simular_es(reqs, FCFS(), DiscoHDD(), "interrupcao", cache=CacheLRU(16, "write-back"), queda_ms=10.0)
        wt = simular_es(reqs, FCFS(), DiscoHDD(), "interrupcao", cache=CacheLRU(16, "write-through"), queda_ms=10.0)
        self.assertEqual((wb["perdidos_na_queda"], wb["escritas_fisicas"]), (5, 0))
        self.assertEqual((wt["perdidos_na_queda"], wt["escritas_fisicas"]), (0, 5))


if __name__ == "__main__":
    unittest.main()
