# Validação de lançadores — 9 e 10 de outubro de 2026

Os testes usam diretórios XDG temporários. Os menus, lançadores e preferências
reais do usuário não são modificados pelos cenários. As duas implementações
(4.0 e 5.8) são verificadas com GTK 3, Gio e CMenu reais.

## Resultado final

152 testes passaram: 87 de Python, 23 de JavaScript e 42 de GTK/CMenu
(21 para cada implementação). As 360 operações combinadas e os 72 ciclos de
salvamento/recarregamento estão incluídos nos testes de GTK/CMenu.

Os registros e as capturas locais são artefatos gerados, excluídos do Git.
Os registros incluem mensagens esperadas de conflitos simulados; nenhuma
asserção falhou. A rodada final usa janelas reais em tela isolada, com avisos
críticos tratados como falhas. Veja a [validação 5.7.0](VALIDACAO-5.7.0.md).

## Cobertura

- Criação com validação obrigatória do comando e persistência após recarregar.
- Duplicação com edição independente e destino preservado.
- Mover e adicionar a categorias, incluindo lotes de lançadores pessoais e do sistema.
- Remoção local sem afetar outras categorias e remoção global de lançadores pessoais.
- Ocultação global, restauração e conservação das associações com categorias.
- Categorias aninhadas, metadados, traduções e ações dos arquivos desktop.
- Desfazer, refazer, descartar, cancelamento de diálogos e execução dos botões reais.
- Conflitos com edição externa, falha de gravação depois de excluir um arquivo,
  reversão da transação e recuperação após interrupção.
- 360 operações geradas com sementes reproduzíveis (11, 73 e 2026), verificadas
  contra um estado esperado independente, com 72 salvamentos/recarregamentos.
- Preservação dos arquivos de aplicativos do sistema em todos os cenários.

## Problemas encontrados e corrigidos

1. CMenu omite lançadores com `Hidden=true`, perdendo suas associações durante o
   recarregamento. As substituições pessoais agora conservam essas associações
   em `X-Canellia-Category-Memberships`, validado ao carregar.
2. A duplicação herdava o campo `Categories` e podia aparecer novamente nas
   categorias do original. A cópia agora recebe exclusões explícitas nas outras
   categorias, mantendo a categoria de destino escolhida.

## Reprodução

```sh
python3 scripts/check.py
bash scripts/run_gtk_suite.sh
```

O primeiro comando requer Node.js 22+, gettext e Bash. O segundo requer uma
sessão gráfica, GTK 3, PyGObject e CMenu; pode ser executado com `xvfb-run`.
Os cenários Flatpak validam a identificação de lançadores, sem instalar ou
remover pacotes reais. Os testes não garantem todas as combinações possíveis de
menus de terceiros, temas, versões do Cinnamon ou condições de falha de hardware.
