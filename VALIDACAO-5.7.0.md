# Canellia 5.7.0 — validação de robustez

Executado em 9 e 10 de outubro de 2026, Cinnamon 6.6.9, X11, monitor 1920 × 1080.
A versão foi instalada e recarregada na sessão real.

151 testes automatizados passaram: 86 Python, 23 JavaScript e 42 GTK/CMenu
(21 em cada implementação). Os cenários incluem 360 operações de lançadores,
72 ciclos de salvamento/recarregamento e 2.000 expressões aritméticas geradas
com sementes reproduzíveis. A suíte GTK usa janelas reais em uma tela isolada,
com `G_DEBUG=fatal-criticals`: nenhum aviso crítico GTK/GDK é tolerado.

## Entregas

- Aba Ferramentas com diagnóstico de comandos, ícones e possíveis duplicatas,
  abertura do lançador correspondente no editor e prévia de aparência.
- Restauração de backups com verificação de conteúdo e de alterações externas;
  cada restauração cria uma nova transação reversível. Recuperação verifica
  todos os arquivos antes de escrever; registros inválidos são preservados.
- Perfis Compacto, Grade e Lista, importação/exportação JSON e restauração das
  preferências anteriores. Validação de tipos, opções, limites e versões.
- Calculadora limitada a operações matemáticas, sem execução de JavaScript.
- Listas paginadas em 200 itens, navegação por Ctrl+PageUp/Ctrl+PageDown,
  reaproveitamento de botões e limpeza dos resultados temporários.
- Pesquisa com estado de processamento, contagem e explicação para ausência de
  resultados; nomes acessíveis e navegação segura quando a lista está vazia.
- Propriedades abre o editor integrado no aplicativo escolhido.
- Favoritos com inserção, reordenação, inclusão ao final e proteção contra
  duplicatas ao soltar um item sobre ele mesmo.
- Favoritos Firefox/LibreWolf sem libgda, incluindo perfis nativos/Flatpak,
  dados confirmados em WAL, URLs inválidas e bases danificadas.
- Metadados de categorias e backups versionados, com leitura do formato anterior.
- Gravação atômica das preferências e traduções dos novos controles em português,
  com catálogos por versão para evitar traduções antigas em cache.
- Validação dos novos módulos e auxiliares no instalador e na integração contínua.

## Sessão real

O teste de execução validou a abertura do menu, a grade, Ctrl+F, pesquisa exata,
cálculo `2+3*4`, ausência de resultados, navegação por 450 itens e execução de
`/usr/bin/true` pelo botão real. Doze ciclos de abertura/fechamento mantiveram o
cache com 109 botões, sem crescimento; os favoritos permaneceram inalterados.
Escape fechou o menu. O estado anterior do menu e suas dimensões foram restaurados.

A janela nativa validou as seis abas, diagnóstico dos lançadores instalados,
prévia e aplicação de perfil em preferências temporárias. O comando de
Propriedades selecionou o lançador e não criou edições pendentes. Os testes de
perfis também verificaram recusa de valores inválidos, conflitos externos e
restauração das preferências anteriores.

## Evidências

- [Verificações gerais](test-results/gauntlet-2026-10-09/checks.txt)
- [GTK/CMenu estrito](test-results/gauntlet-2026-10-09/gtk-cmenu.txt)
- [Execução real](test-results/gauntlet-2026-10-09/runtime.json)
- [Janela nativa](test-results/gauntlet-2026-10-09/native-settings.txt)
- [Propriedades](test-results/gauntlet-2026-10-09/properties.txt)
- [Instalação](test-results/gauntlet-2026-10-09/install.txt)
- Capturas: [diagnóstico](test-results/gauntlet-2026-10-09/screenshots/diagnostico.png),
  [backups](test-results/gauntlet-2026-10-09/screenshots/backups.png),
  [perfis](test-results/gauntlet-2026-10-09/screenshots/perfis.png) e
  [prévia](test-results/gauntlet-2026-10-09/screenshots/previa.png).

## Reprodução e limites

```sh
python3 scripts/check.py
bash scripts/run_gtk_suite.sh
python3 scripts/desktop_runtime_smoke.py --instance 15 --output /tmp/canellia-runtime.json
python3 scripts/native_settings_smoke.py
python3 scripts/properties_smoke.py
```

O identificador 15 corresponde à instância usada nesta sessão. A execução real
requer Cinnamon e `xdotool`; as capturas requerem `gnome-screenshot`. A suíte
estrita requer Xvfb ou Xephyr; os testes devem usar Python com PyGObject/CMenu.
Mensagens de conflitos, arquivos corrompidos e falhas de gravação simuladas nos
registros são resultados esperados desses cenários e possuem tratamento.

Problemas de lançadores externos são apresentados para revisão, sem excluir
aplicativos ou alterar seus arquivos automaticamente. A validação da sessão real
não certifica Wayland, versões antigas do Cinnamon, todos os temas/escalas nem
falhas de hardware. Essas combinações precisam de suas próprias execuções.
