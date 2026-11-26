# Relatório — SimES: simulador de E/S e de sistema de arquivos

**Integrantes:** Isadora Santos da Silva e Nathan Schmitt

**Repositório:** https://github.com/doraslva/sisop-t2 (o projeto está na pasta `Trabalho_IO_2026II/`)

## 0. Resumo

Implementamos o núcleo do SimES e o módulo M1. O núcleo inclui os escalonadores SSTF e SCAN, o custo de CPU por polling e por interrupção e o sistema de arquivos (resolução de caminhos, as oito operações, as tabelas de arquivos abertos e o unlink adiado). O M1 é uma cache de blocos LRU e FIFO, com write-through e write-back. Todos os testes do núcleo e do M1 passam, assim como 27 testes extras escritos pelo grupo. Os três resultados mais importantes foram:

1. O SSTF teve a menor resposta média nas quatro cargas, mas o ganho é limitado pela latência rotacional: nas rajadas, o deslocamento caiu 94% e a resposta só 45%. Já o SCAN, por ir sempre até a borda do disco, ficou 68% pior que o FCFS na carga concentrada.
2. O polling consumiu de 86% a 100% da CPU com o disco rígido, mas no dispositivo rápido gastou a metade da CPU da interrupção, porque ali transferir um bloco (0,008 ms) é mais rápido que tratar uma interrupção e copiar o bloco (0,017 ms).
3. A LRU acertou até 8,3 pontos percentuais a mais que a FIFO, e as duas saturaram em 67% de acertos a partir de 1.024 blocos. O write-back reduziu as escritas físicas em até 48%, mas perdeu até 55 blocos na queda de energia. Além disso, ao despejar até 143 blocos de uma vez a cada 5 s numa fila FCFS, fez leituras esperarem até 1,4 s.

## 1. Escopo realizado

| Parte | Situação | Observação |
|---|---|---|
| N1 · Dispositivo (fornecido) | usado | — |
| N2 · Subsistema de E/S (SSTF, SCAN, polling, interrupção) | completo | SSTF e SCAN conferem com o exemplo do livro (236 cilindros no SSTF; 236 e 331 no SCAN, descendo e subindo); 10 testes extras |
| N3 · Sistema de arquivos | completo | todas as regras de custo conferidas pelos testes; o unlink de um arquivo aberto adia a liberação até o último close; 11 testes extras |
| N4 · Experimentos X1–X5 e relatório | completo | 33 execuções oficiais, mais uma análise complementar de X1 em `resultados/extras/` |
| M1 · Cache de blocos | completo | LRU e FIFO, write-through e write-back; X6 com 25 execuções; 6 testes extras |
| Integração (grupos de 4) | não se aplica | grupo de 2 integrantes |
| Bônus flash | não feito | — |

Resultado dos testes automáticos (`python3 executar.py testes`): `Ran 53 tests` — `OK (skipped=8)`. Os 8 testes pulados são dos módulos M2 a M6 e da integração, que estão fora do escopo do grupo; todos os demais (26 fornecidos e 27 extras, em `testes/test_extras.py`) passam.

## 2. Implementação

### N2 — Subsistema de E/S

**Onde:** `simes/es/escalonadores.py` (auxiliares `_mais_proxima` e `_a_frente`, `SSTF.escolher` e `SCAN.escolher`) e `simes/es/cpu.py` (`custo_cpu`, modos `polling` e `interrupcao`).

**Decisões:** Dois auxiliares concentram as regras comuns do arquivo. `_mais_proxima` escolhe a requisição de menor distância até a cabeça e, no empate, a de menor índice na fila (a que chegou antes). `_a_frente` filtra as requisições à frente na direção atual, contando o cilindro da própria cabeça como "à frente" nas duas direções.

- **SSTF:** aplica `_mais_proxima` à fila inteira e devolve a direção do movimento feito, mantendo a direção atual quando o alvo está no cilindro da cabeça.
- **SCAN:** aplica `_mais_proxima` só às requisições à frente. Se não houver nenhuma, coloca a borda da direção atual em `passar_por`, inverte a direção e escolhe a mais próxima a partir da borda. Caso especial: se a cabeça já está na borda, `passar_por` fica vazio. Passar pela borda chamaria `disco.mover`, que zera `ultimo_bloco` e faria o modelo cobrar uma latência rotacional que não existiu.
- **Custo de CPU:** em `cpu.py`, o polling devolve a duração do atendimento, e a interrupção devolve n_blocos × (`CUSTO_INTERRUPCAO_MS` + `CUSTO_COPIA_MS_POR_BLOCO`), exatamente como nas fórmulas do arquivo.

**Dificuldades:** A principal foi a semântica de `passar_por` no SCAN. O deslocamento até a borda é contado à parte, pelo simulador (com `disco.mover`) e pelo utilitário `percorrer`; por isso, a distância até a borda não pode entrar também na distância até a requisição. Conferimos o resultado com o exemplo do livro nas duas direções e com um teste extra que mede, no simulador, a ida até o cilindro 4.999.

### N3 — Sistema de arquivos

**Onde:** `simes/arquivos/sistema.py`: auxiliares `_descer`, `_pai_e_nome`, `_criar_entrada` e `_inteiro_nao_negativo`, e as operações `resolver`, `mkdir`, `create`, `open`, `read`, `write`, `seek`, `close` e `unlink`.

**Decisões:**

- **Resolução de caminhos:** uma única travessia (`_descer`) parte da raiz. Para cada componente, ela confere se o FCB atual é um diretório (senão, `ENOTDIR`), lê o bloco dele (1 leitura) e procura o nome (senão, `ENOENT`). O `resolver` aplica essa travessia ao caminho inteiro. As operações que criam ou removem entradas usam `_pai_e_nome`, que desce até o pai e lê o pai: o mesmo número de leituras do `resolver` no caminho completo, como pedem as regras de custo.
- **Criação:** `_criar_entrada` cria o FCB, chama o alocador e só então registra o nome no pai. Se o alocador lançar `ENOSPC`, o FCB é descartado sem deixar entrada órfã. O `mkdir` grava o bloco do novo diretório e o do pai; o `create` grava só o do pai.
- **Tabelas de arquivos abertos:** o `open` cria a entrada global do arquivo (ou reaproveita a existente) e soma 1 ao contador; na tabela do processo, cria uma `EntradaProcesso` com o modo e a posição 0. O `close` grava o bloco do pai se o FCB estiver sujo, remove a entrada do processo (e a tabela do processo, se ela ficar vazia) e decrementa o contador global. Quando o contador zera, a entrada global sai e, se o arquivo já não tiver links, os blocos são liberados.
- **Leitura e escrita:** o modo é conferido antes de qualquer acesso (`EBADF`). O `read` é limitado ao tamanho do arquivo e lê numa só chamada todos os blocos do intervalo, para que a camada de blocos agrupe os consecutivos numa única requisição. O `write` só chama `alocador.estender` quando o fim da escrita passa do último bloco, grava apenas os blocos do intervalo escrito e marca o FCB como sujo. No modo `a`, a posição vai para o fim do arquivo a cada escrita, mesmo depois de um `seek`, como o `O_APPEND` do POSIX. Os ganchos `_verificar_permissao` (no open) e `_verificar_trava` (no read e no write) são chamados, como exige o enunciado.
- **unlink:** remove a entrada do pai, decrementa `links` e grava o pai. Os blocos só são liberados se não houver nenhuma abertura (o arquivo não está na tabela global); se houver, a liberação fica para o último `close`.
- **Casos que as regras não especificam:**
  - handle já usado pelo mesmo processo → `EINVAL`, conferido antes de ler os diretórios;
  - `unlink` de diretório → `EISDIR`, como no Linux;
  - `mkdir` ou `create` em "/" → `EEXIST`;
  - tamanho, n ou posição negativos ou não inteiros → `EINVAL`;
  - `seek` além do fim é permitido, e a escrita seguinte aloca todos os blocos até o novo fim (não há arquivos esparsos);
  - `open` com `w` não trunca o arquivo, porque o modelo não tem `O_TRUNC`.

**Dificuldades:** A primeira foi acertar exatamente as contagens das regras de custo; por exemplo, detectar o `ENOTDIR` de `/a/b/f.txt/x` sem "ler" um arquivo como se fosse diretório. A segunda foi separar os dois contadores envolvidos no unlink adiado: `fcb.links`, que conta entradas de diretório, e o contador da tabela global, que conta aberturas. Os 8 testes fornecidos do sistema de arquivos e 11 testes extras conferem esses casos, inclusive o de dois processos com o arquivo aberto e o de falta de espaço.

### M1 — Cache de blocos

**Onde:** `simes/es/cache.py`: classe base `_CacheOrdenada` e as subclasses `CacheLRU` e `CacheFIFO`.

**Decisões:** As duas políticas compartilham a mesma estrutura: um `collections.OrderedDict` que associa cada bloco ao seu estado (sujo ou não), mantido em ordem de expulsão. O primeiro item é a próxima vítima, o que dá custo O(1) para acerto, inserção e expulsão. A única diferença entre as políticas é o método `_usado`, chamado em todo acerto de leitura ou de escrita: a LRU move o bloco para o fim (`move_to_end`), e a FIFO não faz nada.

- **Escrita:** as duas políticas alocam o bloco na cache (write-allocate, como diz o contrato de `escrever`). O write-through devolve o próprio bloco para ser gravado e nunca o marca como sujo, logo nunca expulsa sujos. O write-back marca o bloco como sujo e devolve só os sujos expulsos.
- **Sincronização e contagem:** `sincronizar` devolve os sujos na ordem da cache e os limpa. `sujos()` lê um contador mantido a cada mudança, sem percorrer a cache.

**Dificuldades:** Um caso de concorrência que o contrato não menciona. No write-back, uma escrita pode marcar como sujo um bloco cuja leitura ainda está na fila do disco; quando a leitura termina, o simulador chama `inserir` para esse mesmo bloco. A implementação mantém o estado sujo, porque a versão da cache é a mais nova; sobrescrevê-la com o conteúdo antigo vindo do disco perderia a escrita. Um teste extra cobre esse caso.

## 3. Experimentos

> As hipóteses abaixo foram escritas antes de qualquer execução dos experimentos, a partir
> do livro, dos parâmetros de `simes/parametros.py` e da caracterização das cargas de
> entrada (número de requisições, fração de leituras, blocos distintos). Elas não foram
> alteradas depois de ver os resultados.

Todos os números vêm dos CSVs gerados por `python3 executar.py experimentos`. Para explicar resultados que esses CSVs não detalham, o script `analise_extra.py` reexecuta as mesmas configurações oficiais de X1 e X6, sem alterar parâmetros, cargas nem simuladores. Ele apenas instrumenta o escalonador e a cache para medir causas: utilização do disco, tempo de serviço, idas do SCAN à borda e tamanho das rajadas de sincronização. Essas medidas ficam em `resultados/extras/` e são sempre citadas como complementares.

### X1 — Escalonadores sob quatro padrões de carga

**Hipótese:** (a) Nas cargas aleatória, concentrada e em rajadas, SSTF e SCAN reduzem o deslocamento total do braço e o tempo de resposta médio em relação ao FCFS, e o SSTF tem a menor resposta média. (b) O ganho é limitado pela latência rotacional: o escalonador só encurta a busca, e os 4,17 ms de meia volta continuam sendo pagos em toda requisição não sequencial; uma requisição aleatória de 8 blocos não deve ficar abaixo de ~5,5 ms de serviço, contra ~10,5 ms no FCFS. (c) O SSTF tem a maior espera máxima nas cargas aleatória e concentrada, porque favorece as requisições perto da cabeça (inanição das distantes); o SCAN tem cauda menor que o SSTF, à custa de deslocamento um pouco maior (vai até a borda antes de inverter). (d) Na carga sequencial, o FCFS é o pior caso: ele alterna entre as regiões dos dois processos (~3.600 cilindros de distância), pagando busca e rotação a cada requisição (~16 ms de serviço para chegadas a cada ~6 ms), e satura; SSTF e SCAN atendem em sequência os blocos contíguos de cada processo, sem busca nem rotação (0,32 ms por requisição), e a resposta cai em ordens de grandeza.

**Fundamentação:** Pelo Silberschatz (seção 10.1.1), o tempo de posicionamento de um disco é a soma do tempo de busca com a latência rotacional; o escalonamento de disco (seção 10.4) só atua sobre a busca, reordenando a fila. O FCFS (10.4.1) é justo, mas não otimiza nada; o SSTF (10.4.2) é uma forma de SJF e, como ela, pode causar inanição; o SCAN (10.4.3) varre o disco de ponta a ponta como um elevador, o que limita a espera de qualquer requisição a cerca de duas varreduras. A seção 10.4.6 observa que SCAN e C-SCAN se saem melhor sob carga pesada por serem menos sujeitos à inanição e que, com fila curta, todos os algoritmos se comportam como o FCFS. No modelo do simulador, busca = 1,0 + 0,003·d ms, rotação = 4,17 ms se o bloco não for o seguinte ao último transferido, e transferência = 0,04 ms por bloco. Para posições uniformes nos 5.000 cilindros, a distância média entre duas requisições é 5.000/3 ≈ 1.667 cilindros (busca ≈ 6 ms), logo ≈ 10,5 ms por requisição de 8 blocos. Na carga aleatória, com chegadas a cada 12,1 ms em média, a utilização do disco no FCFS é ≈ 0,87: perto da saturação, onde a espera em fila cresce como ρ/(1−ρ) e qualquer redução do tempo de serviço reduz muito a fila.

**Configuração:** `experimentos.py`, função `x1`: disco rígido (`DiscoHDD`, cabeça no cilindro 0, direção inicial +1), CPU por interrupção, sem cache; escalonadores FCFS, SSTF e SCAN; cargas padronizadas `cargas/es_sequencial.txt` (2 processos varrendo regiões distantes, P1 lendo a partir do cilindro 312 e P2 escrevendo a partir do 3.906, chegadas a cada 5,96 ms), `es_aleatoria.txt` (posições uniformes, 70% leituras, a cada 12,1 ms), `es_concentrada.txt` (80% das requisições nos primeiros 20% do disco; 84% caíram abaixo do cilindro 1.000) e `es_rajadas.txt` (40 rajadas de 50 requisições simultâneas a cada 600 ms). Todas têm 2.000 requisições de 8 blocos. Indicadores: deslocamento total (cilindros), resposta média e p95 (ms), maior espera em fila (ms) e vazão (req/s).

**Resultados:** Disco rígido, interrupção, 2.000 requisições de 8 blocos por carga (`resultados/es.csv`, experimento X1):

| Carga | Escalonador | Deslocamento (cilindros) | Resposta média (ms) | Resposta p95 (ms) | Maior espera (ms) | Vazão (req/s) |
|---|---|---:|---:|---:|---:|---:|
| sequencial | FCFS | 7.184.093 | 10.241,0 | 19.565,4 | 20.598,1 | 61,5 |
| sequencial | SSTF | 2.336.365 | 17,4 | 32,8 | 37,4 | 167,5 |
| sequencial | SCAN | 2.469.069 | 23,2 | 43,7 | 48,6 | 167,4 |
| aleatória | FCFS | 3.316.472 | 50,1 | 145,1 | 193,5 | 82,5 |
| aleatória | SSTF | 2.631.714 | 21,0 | 48,6 | 116,7 | 82,5 |
| aleatória | SCAN | 3.372.680 | 31,5 | 65,1 | 116,7 | 82,4 |
| concentrada | FCFS | 1.864.164 | 19,8 | 48,6 | 96,0 | 83,8 |
| concentrada | SSTF | 1.613.030 | 15,0 | 37,2 | 130,5 | 83,8 |
| concentrada | SCAN | 3.338.708 | 33,2 | 68,3 | 118,8 | 83,7 |
| rajadas | FCFS | 3.341.490 | 267,0 | 505,3 | 597,3 | 83,5 |
| rajadas | SSTF | 209.811 | 147,5 | 277,7 | 297,0 | 84,4 |
| rajadas | SCAN | 199.955 | 148,6 | 278,7 | 285,4 | 84,4 |

Medidas complementares das mesmas execuções (`resultados/extras/x1_extras.csv`):

| Carga | Escalonador | Serviço médio por requisição (ms) | Utilização do disco | Fila média na hora da escolha | Idas à borda |
|---|---|---:|---:|---:|---:|
| sequencial | FCFS | 16,27 | 100,0% | 628,9 | — |
| sequencial | SSTF | 5,67 | 94,9% | 3,0 | — |
| sequencial | SCAN | 5,89 | 98,5% | 4,0 | 493 |
| aleatória | FCFS | 10,46 | 86,3% | 4,3 | — |
| aleatória | SSTF | 9,44 | 77,8% | 2,0 | — |
| aleatória | SCAN | 10,89 | 89,7% | 2,7 | 674 |
| concentrada | FCFS | 8,29 | 69,4% | 2,0 | — |
| concentrada | SSTF | 7,91 | 66,3% | 1,6 | — |
| concentrada | SCAN | 10,83 | 90,6% | 2,9 | 663 |
| rajadas | FCFS | 10,50 | 87,7% | 25,5 | — |
| rajadas | SSTF | 5,80 | 49,0% | 25,5 | — |
| rajadas | SCAN | 5,80 | 49,0% | 25,5 | 38 |

Os gráficos (escala logarítmica) estão em `graficos/X1_resposta_media_ms.png`, `graficos/X1_espera_max_ms.png` e `graficos/X1_deslocamento_total.png`.

**Evidências:** resultados/es.csv (experimento=X1); graficos/X1_resposta_media_ms.png; graficos/X1_espera_max_ms.png; graficos/X1_deslocamento_total.png; complementar: resultados/extras/x1_extras.csv

**Análise:** **Profundidade da fila.** O SSTF teve a menor resposta média nas quatro cargas, mas o tamanho do ganho dependeu da profundidade da fila, como antecipa a seção 10.4.6. Nas rajadas, com 50 requisições chegando juntas (fila média de 25,5 na hora de cada escolha), SSTF e SCAN reduziram o deslocamento em 94%, para cerca de 100 cilindros por requisição: praticamente uma varredura do disco por rajada. Mesmo assim, a resposta média caiu só 45% (de 267,0 para 147,5 ms). É a parte (b) da hipótese. O serviço caiu de 10,50 para 5,80 ms, praticamente o piso do modelo: 1,0 ms de busca mínima, cerca de 0,3 ms de busca proporcional à distância, 4,17 ms de rotação e 0,32 ms de transferência. Com a busca quase eliminada, 72% do serviço passa a ser latência rotacional, que nenhum escalonador por cilindro consegue reduzir. Os valores medidos batem com a estimativa da hipótese (~263 ms e ~145 ms).

**Carga aleatória.** Com chegadas a cada 12 ms e fila média de 2 a 4 requisições, o SSTF reduziu o serviço só de 10,46 para 9,44 ms (−10%), e mesmo assim a resposta média caiu 58% (de 50,1 para 21,0 ms) e o p95, 67%. É o efeito de fila descrito na fundamentação: a utilização do disco caiu de 86,3% para 77,8%, e o termo ρ/(1−ρ) caiu de 6,3 para 3,5. Além disso, como no SJF, atender primeiro a requisição mais barata reduz a espera de todas as que estão atrás dela na fila.

**Carga sequencial.** Foi a maior diferença do experimento. O FCFS alternou entre as duas regiões a cada requisição (3.592 cilindros por requisição), com serviço de 16,27 ms para chegadas a cada 5,96 ms. O disco saturou: utilização de 100% e fila média de 629 requisições. A vazão ficou presa na taxa de serviço, 1.000/16,27 = 61,5 req/s, abaixo da taxa de chegada de 167,5 req/s; a resposta média chegou a 10,2 s e cresceria sem limite com uma carga mais longa. SSTF e SCAN acompanharam a chegada (167,5 req/s), com resposta média de 17,4 e 23,2 ms. A hipótese (d) acertou o efeito, mas superestimou a localidade: o serviço médio do SSTF foi de 5,67 ms, e não de 0,32 ms. Como as chegadas alternam entre os dois processos e a fila média tinha só 3 requisições, o braço trocou de região centenas de vezes; só 59% das requisições do SSTF (65% no SCAN) foram atendidas em sequência, sem busca nem rotação. Essa contagem foi feita com o mesmo simulador, separando os atendimentos de menos de 1 ms.

**O que a hipótese não previu no SCAN.** O SCAN especificado no código vai até a borda do disco sempre que não há nada à frente, e com fila curta isso é frequente. Ele foi à borda em 674 das 2.000 escolhas na carga aleatória e em 663 na concentrada. Na aleatória, essas viagens deixaram o deslocamento 2% maior que o do FCFS e a utilização em 89,7%, mas a resposta média ainda caiu 37%: nos períodos de fila longa, que dominam a média e o p95, a varredura atende a fila em ordem. Na carga concentrada, o efeito foi prejudicial. 84% das requisições estão abaixo do cilindro 1.000, e cada subida leva o braço até o cilindro 4.999, então o deslocamento quase dobrou em relação ao FCFS (3,34 contra 1,86 milhão de cilindros), o serviço subiu de 8,29 para 10,83 ms e a resposta média ficou 68% pior (33,2 contra 19,8 ms). É a razão pela qual o livro apresenta o LOOK (10.4.5) e pela qual os escalonadores reais atendem lotes em ordem de setor sem ir até a borda (seção 4).

**Inanição e cauda.** A parte (c) só se confirmou na carga concentrada. Ali o SSTF teve a maior espera máxima (130,5 ms, contra 118,8 do SCAN e 96,0 do FCFS), sinal de que requisições distantes da região quente foram preteridas, embora o p95 do SSTF (37,2 ms) continue o menor. Na aleatória, a maior espera foi a do FCFS (193,5 ms), cuja fila é a mais longa, e SSTF e SCAN empataram (116,7 ms). A inanição clássica do SSTF exige uma fila que nunca esvazie. Com utilização de 66% a 78%, a fila do SSTF esvazia com frequência, e a requisição distante acaba atendida.

**Veredito:** PARCIALMENTE CONFIRMADA

### X2 — Polling × interrupção conforme o dispositivo

**Hipótese:** (a) No disco rígido, o polling consome uma fração de CPU igual à utilização do disco: ~85–90% na carga aleatória e perto de 100% na sequencial (que satura com o FCFS), enquanto a interrupção gasta ~1%, porque custa 8 × (0,015 + 0,002) = 0,136 ms por requisição contra ~10 ms de atendimento. (b) No dispositivo rápido, a relação se inverte: uma requisição de 8 blocos é atendida em 8 × 0,008 = 0,064 ms, menos que o custo das 8 interrupções (0,136 ms), então o polling gasta cerca da metade da CPU gasta pela interrupção. O ponto de equilíbrio do modelo é uma transferência de 0,017 ms por bloco: abaixo disso, esperar ativamente é mais barato que ser interrompido.

**Fundamentação:** O Silberschatz (13.2.1) descreve o polling como espera ocupada: a CPU lê repetidamente o registrador de estado até o dispositivo ficar pronto, o que é eficiente quando o dispositivo responde rápido e desperdício quando ele demora. A interrupção (13.2.2) libera a CPU durante o atendimento, mas cada interrupção tem um custo fixo de salvar o estado, executar o tratador e retomar o processo; a seção 13.7 destaca que interrupções e trocas de contexto pesam no desempenho de E/S. No modelo (`simes/es/cpu.py`), o polling custa toda a duração do atendimento e a interrupção custa n_blocos × (`CUSTO_INTERRUPCAO_MS` + `CUSTO_COPIA_MS_POR_BLOCO`), independente da duração; portanto, o polling fica proporcional à lentidão do dispositivo, e a interrupção, ao volume transferido.

**Configuração:** `experimentos.py`, função `x2`: escalonador FCFS, sem cache; dispositivos `hdd` (parâmetros padrão) e `rapido` (sem busca nem rotação, 0,008 ms por bloco); cargas `es_aleatoria.txt` e `es_sequencial.txt`; modos `polling` e `interrupcao`. Indicador principal: `cpu_es_pct` = 100 × (CPU gasta com E/S) / (instante em que termina a última requisição).

**Resultados:** FCFS, sem cache, 2.000 requisições de 8 blocos (`resultados/es.csv`, experimento X2):

| Dispositivo | Carga | CPU com polling (%) | CPU com interrupção (%) | Resposta média (ms) | Tempo total (s) |
|---|---|---:|---:|---:|---:|
| hdd | aleatória | 86,28 | 1,12 | 50,1 | 24,3 |
| hdd | sequencial | 99,998 | 0,84 | 10.241,0 | 32,5 |
| rápido | aleatória | 0,53 | 1,12 | 0,064 | 24,2 |
| rápido | sequencial | 1,07 | 2,28 | 0,064 | 11,9 |

O gráfico `graficos/X2_cpu.png` mostra a fração de CPU em escala logarítmica.

**Evidências:** resultados/es.csv (experimento=X2); graficos/X2_cpu.png

**Análise:** **(a) Disco rígido.** O polling consumiu 86,3% da CPU na carga aleatória e 99,998% na sequencial, o que é exatamente a utilização do disco (o mesmo valor de 86,3% aparece para o FCFS em `x1_extras.csv`), porque no modelo a CPU fica presa durante todo o atendimento. A interrupção custou 1,12% e 0,84%: são 2.000 requisições × 0,136 ms = 272 ms de CPU, divididos por 24,3 s e 32,5 s de execução. A diferença entre os dois modos é de 77 a 120 vezes. A porcentagem da interrupção foi menor na carga sequencial só porque o FCFS saturou e esticou o tempo total. O custo absoluto é o mesmo nas duas cargas, pois depende apenas do número de blocos transferidos.

**(b) Dispositivo rápido.** A ordem se inverteu, como previsto. O polling gastou 0,53% e 1,07%, e a interrupção, 1,12% e 2,28%: uma razão de 2,125, exatamente 0,136/0,064. A resposta caiu para 0,064 ms, o próprio tempo de atendimento, porque não se formou fila.

**Interpretação.** O custo do polling é proporcional ao *tempo* que o dispositivo leva, e o da interrupção, ao *número de eventos* (um por bloco). O ponto de troca é quando o atendimento de um bloco dura o mesmo que tratar uma interrupção e copiar o bloco: 0,017 ms. Uma requisição ao disco rígido dura cerca de 77 vezes o custo das suas 8 interrupções (10,5 ms contra 0,136 ms); no dispositivo rápido, ela é mais curta que esse custo. É o que a seção 13.2.1 indica: a espera ocupada só compensa quando o dispositivo fica pronto rapidamente. Há duas ressalvas. A primeira é que, no dispositivo rápido, a CPU gasta é baixa nos dois modos (no máximo 2,3%), porque o dispositivo fica ocioso quase todo o tempo; a vantagem do polling pesaria numa carga que o mantivesse ocupado. A segunda é que o modelo cobra da interrupção só o tratamento e a cópia; efeitos indiretos, como a perda de conteúdo das caches do processador, ficam de fora (seção 5).

**Veredito:** CONFIRMADA

### X3 — Acesso sequencial × direto

**Hipótese:** (a) Os acessos por operação de leitura e escrita serão parecidos nas duas cargas (~1 bloco, já que ambas transferem 4 KiB alinhados), mas o tempo por operação será cerca de uma ordem de grandeza maior no banco de dados. (b) No compilador, quase todo read pede o bloco seguinte ao último transferido e custa só a transferência (0,04 ms); apenas o primeiro read de cada arquivo paga busca curta e latência rotacional, e o custo se concentra no open, que lê os diretórios no começo da partição. (c) No banco de dados, cada read e cada write da tabela vai a um bloco aleatório de uma tabela de 64 MiB (16.384 blocos ≈ 256 cilindros): busca curta (1 + 0,003 × ~85 ≈ 1,3 ms) + rotação (4,17 ms) ≈ 5,5 ms por operação; as escritas no log (modo acréscimo) também pagam busca e rotação, porque o braço precisa ir da tabela até o log e voltar. (d) No compilador, as escritas custam exatamente 1 acesso cada, sem realocações: cada `.o` recriado ocupa, por primeiro encaixe, o buraco deixado pelo `.o` removido, que tem o mesmo tamanho.

**Fundamentação:** O Silberschatz (11.2.1 e 11.2.2) distingue o acesso sequencial, em que o ponteiro de posição avança automaticamente a cada leitura, do acesso direto, em que o programa posiciona o ponteiro (seek) em qualquer bloco. A alocação contígua (12.4.1) atende bem aos dois métodos porque o endereço do bloco i é calculado sem acessos extras, mas só o acesso sequencial aproveita a contiguidade física: pela seção 10.1.1, o custo dominante de um acesso a disco é o posicionamento (busca + rotação), não a transferência. No modelo, um bloco imediatamente seguinte ao último transferido não paga rotação nem busca, e por isso uma varredura sequencial custa 0,04 ms por bloco, enquanto um acesso aleatório custa mais de 5 ms.

**Configuração:** `experimentos.py`, função `x3`: alocador contíguo, partição de 320.000 blocos, sistema de arquivos sem cache. Carga `cargas/fs_compilador.txt` (3.904 operações: 40 fontes e 15 cabeçalhos lidos por inteiro em pedaços de 4 KiB em 3 compilações, com criação e escrita dos `.o`; 600 open, 1.719 read, 726 write, 80 unlink) e `cargas/fs_banco_dados.txt` (6.602 operações: tabela de 64 MiB aberta em `rw` e log em `a`; 3.000 transações com seek aleatório, 80% leituras de 4 KiB e 20% escritas de 4 KiB seguidas de 512 bytes no log). Indicadores: acessos e tempo por operação (`arquivos_por_operacao.csv`) e totais (`arquivos.csv`).

**Resultados:** Acessos e tempo médios por operação, alocação contígua (`resultados/arquivos_por_operacao.csv`, experimento X3):

| Operação | Compilador: n | Acessos/op | Tempo/op (ms) | Banco de dados: n | Acessos/op | Tempo/op (ms) |
|---|---:|---:|---:|---:|---:|---:|
| open | 600 | 3,00 | 8,20 | 2 | 2,00 | 4,25 |
| read | 1.719 | 1,00 | 1,48 | 2.405 | 1,00 | 5,49 |
| write | 726 | 1,00 | 0,91 | 1.190 | 1,00 | 5,54 |
| seek | — | — | — | 3.000 | 0,00 | 0,00 |
| close | 600 | 0,20 | 1,05 | 2 | 1,00 | 4,84 |
| create | 175 | 4,00 | 11,95 | 2 | 3,00 | 8,46 |
| unlink | 80 | 4,00 | 13,69 | — | — | — |

Totais (`resultados/arquivos.csv`): o compilador fez 3.904 operações, 5.400 acessos (1,38 por operação) e 11.986,7 ms de disco (3,07 ms por operação); o banco de dados fez 6.602 operações, 3.610 acessos (0,55 por operação) e 19.847,0 ms (3,01 ms por operação). Nas duas cargas, `realocacoes=0` e `descontinuidades_medias=0.0`. O gráfico está em `graficos/X3_tempo_por_operacao.png`.

**Evidências:** resultados/arquivos_por_operacao.csv (experimento=X3); resultados/arquivos.csv (experimento=X3); graficos/X3_tempo_por_operacao.png

**Análise:** **(a) Acessos e tempo.** Os acessos por operação foram idênticos: 1,00 por read e por write nas duas cargas, como previsto (4 KiB alinhados equivalem a 1 bloco). No tempo, o read do banco (5,49 ms) custou 3,7 vezes o do compilador (1,48 ms), e o write, 6,1 vezes (5,54 contra 0,91 ms). A diferença é grande, mas não chegou à ordem de grandeza prevista. E o tempo médio por operação da carga inteira ficou praticamente igual (3,07 ms no compilador, 3,01 ms no banco): o compilador tem 600 opens e 175 creates caros, e o banco tem 3.000 seeks de custo zero, que derrubam sua média para 0,55 acesso por operação. A média geral por operação, portanto, esconde a diferença de método de acesso, que só aparece operação por operação.

**(b) Por que o read do compilador custou 1,48 ms, e não ~0,04 ms.** A hipótese acertou o mecanismo, mas subestimou o peso do primeiro read de cada arquivo. Os arquivos são pequenos: os 480 arquivos lidos (120 fontes e 360 cabeçalhos) têm em média 3,6 blocos (1.719 reads ÷ 480), e os cabeçalhos, só 1 ou 2. O primeiro bloco de cada arquivo custa ≈ 1,0 ms de busca curta + 4,17 ms de rotação, e cada bloco seguinte, 0,04 ms. Isso dá (480 × ~5,2 + 1.239 × 0,04) ÷ 1.719 ≈ 1,48 ms, o valor medido. Por bloco transferido, a leitura sequencial custou 0,04 ms e a direta, 5,49 ms, cerca de 137 vezes mais. O write do compilador segue a mesma conta: o primeiro bloco de cada `.o` paga o posicionamento, e os demais são sequenciais (0,91 ms em média).

O open, com 3 leituras, foi a operação de leitura mais cara do compilador (8,20 ms). Medindo cada open com o mesmo simulador, o custo depende da posição dos diretórios. O open de `/proj/src/...` custou em média 4,29 ms, porque "/", `/proj` e `/proj/src` ocupam os blocos consecutivos 0, 1 e 2 e só o primeiro paga rotação. Já o de `/proj/include/...` custou 9,42 ms e o de `/proj/build/...`, 8,46 ms: esses diretórios ficam nos blocos 3 e 4, e não logo depois de `/proj` (bloco 1), então o open paga uma segunda rotação.

**(c) Banco de dados.** Confirmada com precisão: 5,49 ms por read, contra a estimativa de 5,5 ms (busca de ~1,3 ms dentro dos 256 cilindros da tabela + 4,17 ms de rotação + 0,04 ms de transferência). As escritas, metade na tabela e metade no log, custaram 5,54 ms, um pouco mais, porque o log fica depois do fim da tabela e o braço faz ida e volta.

**(d) Realocações.** Confirmada: `realocacoes=0` e `descontinuidades_medias=0.0`, e cada write custou exatamente 1,00 acesso. Cada `.o` recriado reocupou, por primeiro encaixe, o buraco do `.o` removido, que tinha o mesmo tamanho. Isso também revela um limite do experimento: com a partição quase vazia, a alocação contígua está no seu melhor caso.

**Conclusão.** O número de acessos é o mesmo nas duas cargas; o que muda o custo é a localidade física, a mesma lição da seção 10.1.1 que apareceu no X1.

**Veredito:** PARCIALMENTE CONFIRMADA

### X4 — Custo de resolver caminhos conforme a profundidade

**Hipótese:** (a) O número de acessos por open cresce linearmente e exatamente como d + 1 (a raiz e os d diretórios do caminho), de 2 em d = 1 a 11 em d = 10. (b) O tempo por open cresce bem menos que os acessos: os diretórios da cadeia são criados em sequência e ocupam blocos consecutivos (0, 1, …, d), então só a leitura da raiz paga latência rotacional (4,17 ms) e cada nível a mais custa apenas a transferência de 0,04 ms. Espera-se ≈ 4,2 + 0,04·(d + 1) ms, ou seja, um aumento de ~10% entre d = 1 e d = 10, enquanto os acessos aumentam 5,5 vezes.

**Fundamentação:** O Silberschatz (11.3) apresenta a estrutura de diretórios em árvore e os caminhos absolutos, que partem da raiz e atravessam um diretório por componente; a seção 11.1.2 explica que o open procura o nome na estrutura de diretórios uma vez e guarda o resultado na tabela de arquivos abertos, justamente para que read e write não repitam essa busca. A seção 12.2 lista, entre as estruturas em memória, o cache da estrutura de diretórios, que existe porque a travessia custaria uma leitura de disco por componente. A regra de custo do simulador é exatamente essa: resolver lê "/", depois cada diretório intermediário, 1 leitura por diretório, sem cache.

**Configuração:** `experimentos.py`, função `x4`, com a carga gerada por `simes/cargas_arquivos.py::fs_profundidade(d)` para d = 1 a 10 (exemplo em `cargas/fs_profundidade_exemplo.txt`): cria uma cadeia `/n1/n2/…/nd`, um arquivo `f.txt` de 4 KiB e o abre, lê e fecha 20 vezes (processo P2). Alocador contíguo. Indicadores: acessos e tempo médios por open (`arquivos_por_operacao.csv`, operação `open`).

**Resultados:** Média das 20 aberturas de cada profundidade (`resultados/arquivos_por_operacao.csv`, experimento X4, operação `open`):

| Profundidade d | Acessos por open | Tempo por open (ms) | Previsão 4,17 + 0,04·(d+1) (ms) |
|---:|---:|---:|---:|
| 1 | 2 | 4,25 | 4,25 |
| 2 | 3 | 4,29 | 4,29 |
| 3 | 4 | 4,33 | 4,33 |
| 4 | 5 | 4,37 | 4,37 |
| 5 | 6 | 4,41 | 4,41 |
| 6 | 7 | 4,45 | 4,45 |
| 7 | 8 | 4,49 | 4,49 |
| 8 | 9 | 4,53 | 4,53 |
| 9 | 10 | 4,57 | 4,57 |
| 10 | 11 | 4,61 | 4,61 |

Em todas as profundidades, o read de `f.txt` custou 1 acesso e 0,04 ms, e o close, nenhum acesso. O gráfico está em `graficos/X4_open_por_profundidade.png`.

**Evidências:** resultados/arquivos_por_operacao.csv (experimento=X4, operacao=open); resultados/arquivos.csv (experimento=X4); graficos/X4_open_por_profundidade.png

**Análise:** **Os dois itens se confirmaram com exatidão.** (a) O open fez exatamente d + 1 acessos em todas as profundidades, de 2 a 11. (b) O tempo seguiu exatamente a fórmula 4,17 + 0,04·(d + 1): 4,25 ms em d = 1 e 4,61 ms em d = 10, um aumento de 8,5%, enquanto os acessos aumentaram 5,5 vezes. O mecanismo é o da hipótese. Os `mkdir` em sequência deram aos diretórios os blocos 0, 1, …, d, e o arquivo ficou no bloco d + 1. Depois do read de `f.txt`, o braço está no cilindro 0, então o open não paga busca: paga uma rotação para voltar ao bloco 0 e lê os demais diretórios em sequência, a 0,04 ms cada. Até o read de `f.txt` custa só 0,04 ms, porque vem logo depois do último diretório lido.

**Este resultado é um caso particular e não deve ser generalizado.** O que cresce linearmente com a profundidade é o custo em acessos; o custo em tempo só ficou quase plano porque a disposição física é ideal. O X3 mostra o caso contrário: lá, o open de `/proj/include/...` pagou duas rotações (9,42 ms com só 3 acessos), porque o diretório não está no bloco seguinte ao do pai. Num sistema de arquivos envelhecido, com diretórios espalhados pelo disco, cada nível custaria uma busca e uma rotação (~5 ms), e o open em d = 10 levaria cerca de 50 ms. É por isso que o open guarda o resultado da busca na tabela de arquivos abertos (seção 11.1.2) e que os sistemas reais mantêm um cache de diretórios em memória (seção 12.2). No X4, as 20 aberturas repetidas do mesmo caminho fizeram 20 × (d + 1) leituras; com um cache de diretórios, só as d + 1 da primeira abertura iriam ao disco.

**Veredito:** CONFIRMADA

### X5 — Tabelas de arquivos abertos com vários processos

**Hipótese:** (a) Cada processo tem no máximo 3 entradas na sua tabela (abre 3 páginas por rodada), e a soma das tabelas por processo chega a 24 (8 × 3). (b) A tabela global fica menor que essa soma, limitada ao número de páginas distintas abertas ao mesmo tempo (no máximo 12; espera-se 11–12), porque aberturas do mesmo arquivo por processos diferentes compartilham uma única entrada global. (c) O contador de aberturas passa de 1: cada página é escolhida por um trabalhador com probabilidade 3/12, então em 40 rodadas espera-se que alguma página chegue a 5 ou 6 aberturas simultâneas. (d) O compartilhamento não reduz o custo do open, que continua lendo "/" e "/www" (2 leituras) a cada abertura, pois o modelo não tem cache de diretórios.

**Fundamentação:** O Silberschatz (11.1.2) descreve as duas tabelas de arquivos abertos: a tabela por processo guarda o que é próprio de cada abertura (ponteiro de posição e modo de acesso) e aponta para a tabela global do sistema, que guarda o que é próprio do arquivo (localização no disco, metadados) e um contador de aberturas; a entrada global só é removida quando o contador chega a zero. A seção 12.2.1 coloca as duas tabelas entre as estruturas do sistema de arquivos mantidas em memória.

**Configuração:** `experimentos.py`, função `x5`, carga `cargas/fs_servidor_web.txt` (6.279 operações): 12 páginas HTML de 8 a 96 KiB em `/www`; 8 processos trabalhadores, 40 rodadas; em cada rodada, cada trabalhador abre 3 páginas distintas, todos leem as páginas inteiras em pedaços de 16 KiB e só depois fecham. Alocador contíguo. Indicadores: `max_tabela_global`, `max_tabela_processo`, `max_soma_tabelas_processo` e `max_contador_aberturas` (`arquivos.csv`), mais o custo por operação.

**Resultados:** Carga `servidor_web`, 8 processos, 40 rodadas (`resultados/arquivos.csv` e `resultados/arquivos_por_operacao.csv`, experimento X5):

| Indicador | Previsto na hipótese | Medido |
|---|---|---:|
| Maior tabela de um processo (`max_tabela_processo`) | 3 | 3 |
| Maior soma das tabelas por processo (`max_soma_tabelas_processo`) | 24 | 24 |
| Maior tabela global (`max_tabela_global`) | ≤ 12 (11–12) | 12 |
| Maior contador de aberturas (`max_contador_aberturas`) | 5–6 | 6 |
| Acessos por open | 2 | 2,00 (4,27 ms) |

Por operação: 960 opens (2,00 acessos, 4,27 ms), 4.346 reads de 16 KiB (3,65 acessos, 1,18 ms) e 960 closes (nenhum acesso). No total, 17.824 acessos e 9.354,1 ms de disco, sem erros. O gráfico está em `graficos/X5_tabelas.png`.

**Evidências:** resultados/arquivos.csv (experimento=X5); resultados/arquivos_por_operacao.csv (experimento=X5); graficos/X5_tabelas.png

**Análise:** **Todas as previsões se confirmaram.** A soma das tabelas por processo chegou a 24 entradas (8 trabalhadores × 3 aberturas), enquanto a tabela global nunca passou de 12, o número de páginas. Em algum momento as 12 páginas estavam abertas ao mesmo tempo, mas cada uma ocupou uma única entrada global, compartilhada por até 6 processos (contador máximo de 6). A separação em duas tabelas, descrita na seção 11.1.2, não duplica o que é do arquivo (FCB, localização dos blocos) e mantém separado o que é de cada abertura. Cada trabalhador tem a sua própria posição: o teste `test_tabelas_compartilhadas` mostra P1 na posição 4.096 e P2 na posição 0 sobre a mesma entrada global. Se a posição ficasse na entrada global, os 6 processos que leem a mesma página avançariam um único ponteiro, e cada um leria só pedaços dela.

**O contador e o unlink.** O contador da entrada global também é o que torna seguro o unlink de um arquivo aberto: a entrada só sai, e os blocos só são liberados, quando o contador zera. Isso é conferido pelo teste `test_unlink_com_arquivo_aberto` e pelo teste extra com dois processos.

**O compartilhamento economiza memória, não disco.** Cada um dos 960 opens leu "/" e "/www" de novo (2,00 acessos, 4,27 ms), embora cada página tenha sido aberta 80 vezes em média. Os closes não acessaram o disco, porque as aberturas eram só de leitura e o FCB não ficou sujo. Num sistema real, um cache de diretórios eliminaria o custo do open depois da primeira vez. Do mesmo modo, um cache de páginas evitaria reler as páginas: as 4.346 leituras releram sempre os mesmos 12 arquivos, que é justamente o padrão de reúso explorado no X6.

**Veredito:** CONFIRMADA

### X6 — Cache de blocos (M1)

**Hipótese:** (a) Sem cache, a carga de reúso sobrecarrega o disco com FCFS: cada requisição de 1 bloco numa posição aleatória custa ~10,2 ms (1 + 0,003 × 1.667 + 4,17 + 0,04), e as chegadas ocorrem a cada ~8 ms (utilização ≈ 1,3), então a fila cresce sem limite e a resposta média fica na casa dos segundos; com cache, os acertos (0,001 ms por bloco) e, no write-back, as escritas absorvidas tiram requisições do disco, e a resposta cai em ordens de grandeza. (b) A taxa de acerto cresce com a capacidade, com retornos decrescentes, e satura a partir de 1.024 blocos: a carga toca só 992 blocos distintos, então com 1.024 ou 2.048 blocos não há expulsões e só restam as faltas compulsórias; nessas capacidades, LRU e FIFO empatam. (c) Nas capacidades pequenas (64 a 512), a LRU acerta mais que a FIFO: com a distribuição de Zipf, poucos blocos concentram os acessos, e a LRU os mantém por serem reacessados, enquanto a FIFO os expulsa periodicamente só por terem entrado há mais tempo. (d) A política de escrita quase não muda a taxa de acerto, porque a escolha da vítima depende só da ordem dos blocos; diferenças pequenas podem surgir do momento em que os blocos lidos entram na cache. (e) Write-through grava no disco todas as 1.045 escritas do usuário, em qualquer capacidade, e não perde nada na queda; write-back grava bem menos (escritas repetidas no mesmo bloco são agregadas até a expulsão ou a sincronização a cada 5 s), cada vez menos conforme a capacidade cresce, mas perde dezenas de blocos sujos na queda, e a perda cresce com a capacidade (a cache maior retém sujos em vez de expulsá-los e gravá-los), até o limite dos blocos distintos escritos desde a última sincronização (a queda ocorre em 11.733 ms, 1,7 s depois da sincronização de 10.000 ms).

**Fundamentação:** O Silberschatz (13.4.3) define a cache como uma cópia, em memória rápida, de dados que estão no dispositivo, e a seção 12.6.2 descreve o buffer cache e o cache de páginas e o compromisso das escritas assíncronas: elas terminam assim que os dados chegam à memória, mas o que ainda não foi gravado se perde numa falha (o que motiva a seção 12.7, sobre recuperação). Os algoritmos de substituição são os da memória virtual (9.4.2, FIFO, e 9.4.4, LRU): a LRU aproxima o algoritmo ótimo usando o passado recente como previsão do futuro, o que funciona quando há localidade de referência; a FIFO ignora o uso. Pelas regras do modelo (`simes/es/cache.py` e `simes/es/simulador.py`), a escrita aloca o bloco nas duas políticas, o write-back marca o bloco como sujo e só o grava ao expulsá-lo ou na sincronização a cada `INTERVALO_SYNC_MS` = 5.000 ms, e a perda na queda é o número de blocos sujos no instante da queda.

**Configuração:** `experimentos.py`, função `x6`: carga `cargas/es_reuso.txt` (3.000 requisições de 1 bloco, 65% leituras, Zipf sobre 4.000 páginas, chegadas a cada 7,95 ms; 992 blocos distintos, 1.045 escritas em 469 blocos distintos); FCFS, disco rígido, CPU por interrupção; uma execução sem cache e 24 com cache (LRU e FIFO × capacidades 64, 128, 256, 512, 1.024 e 2.048 blocos × write-through e write-back); queda de energia simulada no instante de chegada da requisição do meio (11.733,2 ms). Indicadores: `acerto_cache_pct` (acertos entre as requisições de leitura), `escritas_fisicas`, `perdidos_na_queda`, resposta média e p95.

**Resultados:** Carga `reuso`, FCFS, disco rígido, queda em 11.733,2 ms (`resultados/es.csv`, experimento X6). Sem cache: resposta média de 3.500,0 ms, p95 de 6.427,5 ms, maior espera de 6.936,3 ms, 1.045 escritas físicas e tempo total de 30,8 s. Com cache:

| Política | Capacidade (blocos) | Acerto WT (%) | Acerto WB (%) | Escritas físicas WT | Escritas físicas WB | Perdidos WT | Perdidos WB | Resposta média WT (ms) | Resposta média WB (ms) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| LRU | 64 | 39,64 | 39,64 | 1.045 | 715 | 0 | 28 | 74,7 | 23,4 |
| LRU | 128 | 48,85 | 49,10 | 1.045 | 630 | 0 | 51 | 33,4 | 26,2 |
| LRU | 256 | 57,75 | 57,70 | 1.045 | 543 | 0 | 55 | 22,0 | 47,6 |
| LRU | 512 | 64,19 | 64,25 | 1.045 | 541 | 0 | 55 | 18,2 | 45,4 |
| LRU | 1.024 | 67,06 | 67,01 | 1.045 | 541 | 0 | 55 | 16,9 | 38,9 |
| LRU | 2.048 | 67,06 | 67,01 | 1.045 | 541 | 0 | 55 | 16,9 | 38,9 |
| FIFO | 64 | 31,30 | 33,09 | 1.045 | 810 | 0 | 22 | 436,1 | 46,3 |
| FIFO | 128 | 42,56 | 43,89 | 1.045 | 706 | 0 | 46 | 51,7 | 29,9 |
| FIFO | 256 | 53,20 | 53,30 | 1.045 | 607 | 0 | 50 | 25,9 | 46,3 |
| FIFO | 512 | 60,56 | 60,10 | 1.045 | 567 | 0 | 50 | 20,5 | 47,2 |
| FIFO | 1.024 | 67,06 | 67,01 | 1.045 | 541 | 0 | 55 | 16,9 | 39,7 |
| FIFO | 2.048 | 67,06 | 67,01 | 1.045 | 541 | 0 | 55 | 16,9 | 39,7 |

(WT = write-through; WB = write-back.)

Medidas complementares da LRU nas mesmas execuções (`resultados/extras/x6_extras.csv`); sem cache, a utilização do disco foi de 99,98%:

| Capacidade | Utilização do disco WT / WB | Resposta média das leituras WT / WB (ms) | p95 das leituras WT / WB (ms) | Maior espera das leituras WT / WB (ms) | Rajada de sincronização WB: média (máx.) | Sujos expulsos WB |
|---:|---:|---:|---:|---:|---:|---:|
| 64 | 94,6% / 80,6% | 61,2 / 35,8 | 207,5 / 156,3 | 257,5 / 418,4 | 27,5 (29) | 605 |
| 128 | 87,9% / 70,2% | 24,6 / 40,3 | 99,4 / 276,7 | 155,9 / 690,2 | 62,0 (66) | 382 |
| 256 | 80,5% / 58,5% | 15,0 / 73,1 | 66,7 / 643,7 | 151,8 / 1.271,1 | 109,8 (122) | 104 |
| 512 | 74,9% / 52,3% | 11,6 / 69,7 | 55,9 / 673,5 | 151,8 / 1.416,8 | 135,3 (143) | 0 |
| 1.024 | 72,5% / 50,1% | 10,5 / 59,7 | 54,1 / 543,4 | 151,8 / 1.416,8 | 135,3 (143) | 0 |

Os gráficos estão em `graficos/X6_acerto.png` (acerto × capacidade, write-back) e `graficos/X6_escrita.png` (escritas físicas e perdas, LRU).

**Evidências:** resultados/es.csv (experimento=X6); graficos/X6_acerto.png; graficos/X6_escrita.png; complementar: resultados/extras/x6_extras.csv

**Análise:** **(a) Saturação sem cache.** Sem cache, o disco saturou como previsto: utilização de 99,98%, tempo total de 30,8 s para chegadas que terminam em 23,8 s, resposta média de 3,5 s e p95 de 6,4 s. Com qualquer cache, a resposta média caiu de 8 a 207 vezes: ficou entre 16,9 e 74,7 ms na LRU e entre 16,9 e 436,1 ms na FIFO. O pior caso, FIFO com 64 blocos em write-through, acertou só 31% das leituras e manteve o disco a 99,8% de utilização. Bastaram mais acertos (FIFO com 128 blocos) para a resposta cair para 51,7 ms. Perto da saturação, cada requisição a menos no disco vale muito, como já se viu no X1.

**(b) e (c) Taxa de acerto e capacidade.** A taxa de acerto cresceu de forma côncava com a capacidade e saturou em 67,06% a partir de 1.024 blocos. Nessa faixa, LRU e FIFO ficaram idênticas, e as execuções com 2.048 blocos repetiram as de 1.024 em todos os indicadores, porque os 992 blocos distintos cabem inteiros na cache. Os 33% restantes são faltas compulsórias, o primeiro acesso a cada bloco. Abaixo de 1.024 blocos, a LRU sempre acertou mais: 8,3 pontos percentuais a mais com 64 blocos (39,6% contra 31,3% em write-through), 6,3 com 128, 4,6 com 256 e 3,6 com 512. Com Zipf, poucos blocos concentram os acessos, e a LRU os mantém justamente por serem reacessados; a FIFO os expulsa a cada volta da fila. A vantagem diminui com a capacidade porque, numa cache maior, um bloco quente sobrevive mais tempo até mesmo na FIFO.

**(d) Política de escrita e acerto.** A política de escrita mudou a taxa de acerto em no máximo 1,8 ponto (FIFO com 64 blocos: 31,3% contra 33,1%) e, a partir de 256 blocos, em menos de 0,5 ponto, porque a escolha da vítima depende só da ordem dos blocos. A diferença residual vem do momento em que um bloco lido entra na cache: só quando a leitura termina no disco, o que depende da fila, mais longa no write-through.

**(e) Escritas físicas e perdas.** O write-through gravou as 1.045 escritas do usuário em todas as capacidades e não perdeu nada na queda. O write-back gravou de 810 (FIFO, 64 blocos) a 541 blocos, uma economia de 22% a 48%. Em troca, perdeu de 22 a 55 blocos sujos na queda, número que cresce com a capacidade e satura em 55, como previsto. Os números fecham com a mecânica medida na análise complementar. A partir de 512 blocos, a LRU não expulsou nenhum sujo, e as 541 escritas físicas são exatamente as 4 sincronizações (135,25 blocos em média). Com 64 blocos, 605 expulsões de sujos substituíram boa parte das sincronizações, que caíram para 27,5 blocos cada. As 1.045 escritas do usuário caem em só 469 blocos distintos, e o write-back grava cada bloco no máximo uma vez por intervalo de 5 s.

**O que a hipótese não previu: o write-back piorou a resposta das leituras.** A partir de 256 blocos, a resposta média com write-back foi de 1,8 a 2,5 vezes a do write-through (LRU com 512 blocos: 45,4 contra 18,2 ms). A maior espera saltou para 1,1 a 1,4 s, contra 0,15 s no write-through. Isso aconteceu com o disco menos ocupado (utilização de 52% contra 75%) e com as escritas terminando em 0,001 ms. A análise complementar mostra a causa. A cada 5 s, a sincronização despeja todos os sujos de uma vez na fila FCFS: até 143 escritas aleatórias de ~10 ms cada, cerca de 1,4 s de trabalho. Toda leitura que chega nesse intervalo espera atrás delas; nas leituras, a média passou de 11,6 ms (write-through) para 69,7 ms (write-back), e o p95, de 56 para 673 ms.

Quanto maior a cache, menos sujos são expulsos aos poucos e maiores ficam as rajadas; por isso o efeito piora com a capacidade. Com 64 blocos, as expulsões espalham as gravações no tempo, e o write-back foi melhor que o write-through nas leituras (35,8 contra 61,2 ms), porque tirou 330 escritas de um disco que estava a 95% de utilização. Em resumo, o write-back reduz o *volume* de escrita, mas, sem um escalonador que priorize leituras e sem espalhar a gravação no tempo, concentra esse volume em rajadas que prejudicam a latência. São exatamente os dois problemas que os sistemas reais tratam (seção 4). Esse efeito não contradiz nenhuma das previsões (a) a (e), mas é a observação mais importante do experimento.

**Veredito:** CONFIRMADA

## 4. Relação com sistemas reais

As fontes estão numeradas na seção 7.

**Escalonamento de disco (X1).** No Linux, o escalonador é escolhido por dispositivo, escrevendo o nome em `/sys/block/<dispositivo>/queue/scheduler` [5].

- **mq-deadline:** mantém cada requisição em duas listas, uma ordenada por setor e uma FIFO com prazo, e atende lotes em ordem crescente de setor, com preferência para as leituras. Os prazos padrão são de 500 ms para leitura e 5 s para escrita, e o parâmetro `writes_starved` (2, por padrão) limita quantas vezes as leituras passam na frente das escritas [2][3]. É a combinação dos dois lados do X1: a ordenação por posição dá o ganho de vazão que vimos no SSTF, e o prazo corta a cauda que o SSTF produziu na carga concentrada. Como os lotes são atendidos em ordem de setor sem viagem obrigatória até a borda, ele também evita o desperdício que fez o SCAN piorar na carga concentrada. Os prazos de `PRAZO_LEITURA_MS` e `PRAZO_ESCRITA_MS` do simulador (módulo M2, que não fizemos) são uma versão reduzida desses valores.
- **BFQ:** reparte o disco entre processos em fatias proporcionais. Cada fila de processo recebe um orçamento medido em setores, e as aplicações interativas e de tempo real brando são privilegiadas com menor latência [4]. É um critério de justiça entre processos que nenhum dos algoritmos do X1 considera.
- **none:** apenas repassa as requisições, sem reordenar [5]. O kernel usa por padrão o mq-deadline nos dispositivos de fila única e o none nos que têm várias filas de hardware, caso típico dos SSDs NVMe [5]. O X2 explica a escolha: num dispositivo sem busca nem rotação, reordenar não reduz nada.
- **NCQ:** independentemente do sistema operacional (Windows, Linux ou macOS), um disco SATA com NCQ reordena internamente os comandos pendentes para reduzir a sobrecarga mecânica, usando inclusive a posição rotacional [6]. Isso ataca justamente a parte que o X1 mostrou estar fora do alcance de um escalonador por cilindro: a latência rotacional, que chegou a 72% do serviço do SSTF nas rajadas.

**Polling e interrupção (X2).** O resultado do X2, em que o polling sai mais barato que a interrupção quando o dispositivo responde mais rápido que o custo de tratá-la, é a justificativa do modo de polling do Linux para armazenamento rápido. Com `IORING_SETUP_IOPOLL`, o io_uring faz espera ocupada pela conclusão da E/S em vez de ser notificado por interrupção; para NVMe, o driver precisa ser carregado com filas de polling (`poll_queues`) [7]. Na rede, o NAPI adota um meio-termo: o dispositivo avisa por interrupção, o driver agenda o NAPI e mantém as interrupções mascaradas enquanto processa os eventos, reabilitando-as só quando termina [8]. Paga-se, assim, uma interrupção por lote de eventos, e não por evento; no modelo do X2, seria dividir os 0,136 ms de interrupções de uma requisição por todo o lote.

**Tabelas de arquivos abertos e unlink (X5).** A estrutura do N3 corresponde à do POSIX, com uma simplificação. No Linux, o open cria uma descrição de arquivo aberto (*open file description*), que guarda a posição e os flags de status, e o descritor apenas aponta para ela. Descritores de processos diferentes podem apontar para a mesma descrição, por exemplo depois de um `fork`, e então compartilham também a posição [14]. No simulador, cada abertura tem a sua própria entrada com a posição, e esse compartilhamento não existe.

A semântica do unlink com arquivo aberto do N3 é a do Linux: se o nome era o último link e algum processo ainda tem o arquivo aberto, o arquivo continua existindo até o último descritor ser fechado [15]. O Windows trata o caso de outro modo. `DeleteFile` marca o arquivo para remoção no fechamento, e a remoção só acontece quando o último handle é fechado; além disso, só é possível remover o arquivo se os outros handles tiverem sido abertos com `FILE_SHARE_DELETE` [16].

**Resolução de caminhos e diretórios (X3, X4).** O Linux percorre o caminho componente por componente, como o simulador, mas consulta antes o dcache, que mantém em memória informações sobre os nomes de cada sistema de arquivos; no modo RCU-walk, muitas vezes nem chega a chamar o sistema de arquivos [13]. No X4, isso reduziria as 20 × (d + 1) leituras de cada profundidade a d + 1.

As estruturas de diretório reais também tratam um problema que o modelo esconde ao dar 1 bloco a cada diretório: um diretório grande ocupa muitos blocos, e procurar um nome nele por varredura linear custaria muitas leituras.

- **ext4:** os diretórios grandes usam uma árvore B indexada pelo hash do nome (*htree*) [17].
- **NTFS:** todo arquivo tem ao menos uma entrada na MFT (*Master File Table*); as pastas pequenas cabem inteiras no registro da MFT, e as grandes são organizadas como árvores B [18].
- **APFS:** guarda os registros do sistema de arquivos como pares chave-valor em árvores B e nunca altera um objeto no lugar, gravando a cópia modificada em outra posição (*copy-on-write*) [19].

No X3, a alocação contígua mostrou seu melhor caso, sem realocações nem descontinuidades. O ext4 substituiu o mapa de blocos por uma árvore de extents [17] e, com isso, conserva a vantagem da contiguidade sem exigir que o arquivo inteiro seja contíguo.

**Cache de blocos e gravação adiada (X6).**

- **Intervalo de gravação:** o intervalo de sincronização do simulador, 5 s, é o mesmo do Linux, cujas threads de flush acordam periodicamente a cada `dirty_writeback_centisecs` = 500 centésimos de segundo [9]. A diferença está no que é gravado: a cada despertar, o Linux grava os dados que estão sujos há mais de `dirty_expire_centisecs` = 3.000 (30 s) [9], e não todos os sujos, como o simulador.
- **Windows:** o "lazy writer" do gerenciador de cache roda a cada segundo e enfileira para gravação um oitavo das páginas que não foram gravadas recentemente [11].
- **Espalhar no tempo:** as duas estratégias espalham a gravação no tempo, o oposto da rajada de até 143 blocos a cada 5 s que, no X6, fez leituras esperarem até 1,4 s. Somadas à preferência do mq-deadline pelas leituras [2], evitam que o write-back troque volume de escrita por latência de leitura, como aconteceu no simulador com FCFS.
- **Preço da perda na queda:** existe nos três sistemas, e por isso todos oferecem formas de forçar a gravação. No Windows, há o write-through por arquivo, em que o dado também fica na cache (como no modelo) mas é gravado imediatamente, e a função `FlushFileBuffers` [11]. No macOS, o manual do `fsync` adverte que o próprio disco pode manter os dados no seu cache interno por bastante tempo e gravá-los fora de ordem, e oferece o `fcntl` `F_FULLFSYNC` para pedir ao disco que grave tudo no meio permanente [12]. É uma segunda camada de write-back, dentro do disco, que o modelo não tem.
- **Substituição:** os sistemas reais não usam uma LRU exata. O Linux aproxima a LRU com listas de páginas ativas e inativas e oferece como alternativa a multi-gen LRU (MGLRU), que generaliza essas listas em gerações [10]. A premissa é a mesma que o X6 confirmou: com localidade, o passado recente prevê o futuro, mas manter uma ordem exata a cada acesso seria caro demais.

## 5. Limitações do simulador

- **Rotação sem posição angular.** A latência rotacional é sempre a média (4,17 ms) quando o bloco não é o seguinte ao último transferido; o disco não tem posição angular. Por isso nenhum escalonador consegue reduzir a rotação, o que limitou os ganhos do X1 (parte b). Discos reais com NCQ reordenam também pela posição rotacional [6], e o ganho do escalonamento seria maior do que o medido.
- **Busca e cache do disco.** A busca é linear na distância (1,0 + 0,003·d ms). Não há zonas com densidades diferentes, buffer de trilha, leitura antecipada nem cache no disco. A sequencialidade só é reconhecida se o bloco for exatamente o seguinte; um salto pequeno paga a rotação inteira.
- **Fila sem fusão.** O disco atende uma requisição por vez e não funde requisições adjacentes da fila, como o Linux faz. Na carga sequencial do X1, a fusão reduziria ainda mais o custo das varreduras.
- **Sistema de arquivos sem caches nem diário.** O sistema de arquivos não tem cache de diretórios, de FCBs nem de dados, nem leitura antecipada. Por isso X3, X4 e X5 superestimam os acessos ao disco em relação a um sistema real (cada open relê todos os diretórios do caminho). Cada diretório ocupa 1 bloco, independentemente do número de entradas, e os metadados só são gravados no close, sem diário (o ext4 e o NTFS usam diário; o APFS usa copy-on-write [19]).
- **Partição recém-formatada.** Os experimentos do sistema de arquivos começam com o disco vazio, então a alocação contígua está no seu melhor caso (sem realocações nem descontinuidades no X3), e os diretórios ficam em blocos consecutivos. O tempo quase constante do open no X4 é consequência dessa disposição ideal, e não uma propriedade da resolução de caminhos.
- **Modelo de CPU.** O polling custa toda a duração do atendimento, sem polling híbrido; a interrupção custa um valor fixo por bloco, sem agrupamento de interrupções nem efeitos indiretos (troca de contexto do processo bloqueado, perda de conteúdo das caches do processador). O ponto de troca do X2 (0,017 ms por bloco) depende desses dois parâmetros.
- **Cache fora do sistema de arquivos.** No X6, a cache atua sobre requisições de blocos, e não sobre as operações do sistema de arquivos. A sincronização grava todos os sujos de uma vez numa fila FCFS, sem prioridade para leituras; parte da piora de latência do write-back vem dessa escolha do modelo, e não do write-back em si. A perda na queda é medida como o número de blocos sujos, sem avaliar a consistência dos metadados. A simulação também termina sem uma sincronização final, então os sujos que restam no fim (escritos depois da última sincronização) não entram nas `escritas_fisicas` do write-back, que ficam um pouco subestimadas.
- **Uma semente por carga.** As cargas são sintéticas, com uma semente fixa e uma execução por configuração; não há intervalos de confiança. Diferenças pequenas, como a de 0,1 ms entre SSTF e SCAN nas rajadas ou as de menos de 0,5 ponto de acerto entre as políticas de escrita, não devem ser tomadas como significativas.

## 6. Conclusões

1. Escalonar o disco só ajuda na medida em que há fila. O SSTF teve a menor resposta média nas quatro cargas, com ganho de 24% (concentrada) a 99,8% (sequencial, em que o FCFS saturou). Mesmo assim, a latência rotacional impõe um piso de ~5,5 ms por requisição aleatória: nas rajadas, o deslocamento caiu 94% e a resposta, só 45%.
2. O SCAN que sempre vai até a borda é prejudicial com fila curta e carga concentrada. Ele foi à borda em um terço das escolhas e ficou 68% pior que o FCFS na carga concentrada. É o argumento a favor do LOOK e do atendimento em lotes por setor dos escalonadores reais, como o mq-deadline.
3. A escolha entre polling e interrupção depende da relação entre o tempo de atendimento de um bloco e o custo de uma interrupção (0,017 ms no modelo). Com o disco rígido, o polling gastou de 86% a 100% da CPU, contra cerca de 1% da interrupção; no dispositivo rápido, gastou metade da CPU da interrupção. É a mesma lógica do polling para NVMe no Linux.
4. No sistema de arquivos, o número de acessos não determina o custo; a localidade física, sim. Um open com 11 acessos custou 4,61 ms porque os diretórios eram contíguos, enquanto um open com 3 acessos em diretórios não consecutivos custou 9,42 ms. Um read direto custou 5,49 ms por bloco, contra 0,04 ms de um sequencial. As duas tabelas de arquivos abertos separaram o que é do arquivo (12 entradas globais) do que é de cada abertura (24 entradas por processo).
5. Na cache, a LRU superou a FIFO em até 8,3 pontos percentuais, e as duas saturaram em 67% quando a cache passou a conter todos os 992 blocos. O write-back reduziu as escritas físicas em até 48%, mas perdeu até 55 blocos na queda. Além disso, ao sincronizar tudo de uma vez numa fila FCFS, fez leituras esperarem até 1,4 s. Linux e Windows evitam esse efeito espalhando a gravação no tempo e priorizando as leituras.

## 7. Referências

1. SILBERSCHATZ, A.; GALVIN, P. B.; GAGNE, G. *Operating System Concepts*. 9. ed. Wiley, 2013. Seções 9.4, 10.1, 10.4, 11.1–11.3, 12.2, 12.4, 12.6, 12.7, 13.2, 13.4 e 13.7.
2. THE LINUX KERNEL DOCUMENTATION. *Deadline IO scheduler tunables*. https://docs.kernel.org/block/deadline-iosched.html
3. LINUX KERNEL (código-fonte). `block/mq-deadline.c` (valores padrão de `read_expire`, `write_expire`, `writes_starved` e `fifo_batch`). https://github.com/torvalds/linux/blob/master/block/mq-deadline.c
4. THE LINUX KERNEL DOCUMENTATION. *BFQ (Budget Fair Queueing)*. https://docs.kernel.org/block/bfq-iosched.html
5. THE LINUX KERNEL DOCUMENTATION. *Switching Scheduler* (https://docs.kernel.org/block/switching-sched.html) e *Multi-Queue Block IO Queueing Mechanism (blk-mq)* (https://docs.kernel.org/block/blk-mq.html); regra do escalonador padrão em `block/elevator.c`: https://github.com/torvalds/linux/blob/master/block/elevator.c
6. SEAGATE. *Serial ATA (SATA) Native Command Queuing (NCQ) FAQs*. https://www.seagate.com/au/en/support/kb/serial-ata-sata-native-command-queuing-ncq-faqs-193785en/ ; INTEL; SEAGATE. *Serial ATA Native Command Queuing* (white paper), 2003.
7. LINUX MAN-PAGES. *io_uring_setup(2)*. https://man7.org/linux/man-pages/man2/io_uring_setup.2.html
8. THE LINUX KERNEL DOCUMENTATION. *NAPI*. https://docs.kernel.org/networking/napi.html
9. THE LINUX KERNEL DOCUMENTATION. *Documentation for /proc/sys/vm/* (https://docs.kernel.org/admin-guide/sysctl/vm.html); valores padrão em `mm/page-writeback.c`: https://github.com/torvalds/linux/blob/master/mm/page-writeback.c
10. THE LINUX KERNEL DOCUMENTATION. *Multi-Gen LRU*. https://docs.kernel.org/admin-guide/mm/multigen_lru.html e https://docs.kernel.org/mm/multigen_lru.html
11. MICROSOFT. *File Caching* (Win32). https://learn.microsoft.com/en-us/windows/win32/fileio/file-caching
12. APPLE. *fsync(2)*, Mac OS X Manual Page. https://developer.apple.com/library/archive/documentation/System/Conceptual/ManPages_iPhoneOS/man2/fsync.2.html
13. THE LINUX KERNEL DOCUMENTATION. *Pathname lookup*. https://docs.kernel.org/filesystems/path-lookup.html
14. LINUX MAN-PAGES. *open(2)*. https://man7.org/linux/man-pages/man2/open.2.html
15. LINUX MAN-PAGES. *unlink(2)*. https://man7.org/linux/man-pages/man2/unlink.2.html
16. MICROSOFT. *DeleteFileW function*. https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-deletefilew
17. THE LINUX KERNEL DOCUMENTATION. *ext4: Directory Entries* (https://docs.kernel.org/filesystems/ext4/directory.html) e *The Contents of inode.i_block* (https://docs.kernel.org/filesystems/ext4/ifork.html).
18. MICROSOFT. *Master File Table* (https://learn.microsoft.com/en-us/windows/win32/fileio/master-file-table) e *How NTFS Works* (Windows Server 2003): <https://learn.microsoft.com/en-us/previous-versions/windows/it-pro/windows-server-2003/cc781134(v=ws.10)>
19. APPLE. *Apple File System Reference*. https://developer.apple.com/support/apple-file-system/Apple-File-System-Reference.pdf

## 8. Declaração de autoria e uso de IA

**Quem fez o quê:** a preencher pelos integrantes, com a divisão real do trabalho.

[PENDENTE — os integrantes devem descrever aqui a divisão do trabalho e como revisaram o conteúdo gerado com IA]

**Uso de ferramentas de IA:**

| Ferramenta | Finalidade | Onde foi usada (arquivos ou seções) |
|---|---|---|
| Claude Code (Anthropic), assistente de programação com IA, usado no VS Code | Auditoria do código fornecido; escolha do módulo; implementação do N2, do N3 e do M1; testes extras; script de análise complementar; execução dos testes, dos experimentos e dos gráficos; pesquisa e verificação das fontes da seção 4; redação das hipóteses (antes de rodar os experimentos), das análises e do restante do relatório | `simes/es/escalonadores.py`, `simes/es/cpu.py`, `simes/arquivos/sistema.py`, `simes/es/cache.py`, `testes/test_extras.py`, `analise_extra.py`, `grupo.json`, `resultados/`, `graficos/` e todas as seções deste relatório |
