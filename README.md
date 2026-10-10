# Canellia

Um menu para o Cinnamon que ajuda você a encontrar aplicativos, organizar
categorias e deixar a área de trabalho do seu jeito.

**Versão 5.7.0** · [Sobre o projeto](ABOUT.md) · [Licença](LICENSE.md)

![Menu Canellia em execução](screenshot.png)

## O que você pode fazer

- Navegar pelos aplicativos em grade ou lista e organizar seus favoritos.
- Criar, editar, duplicar e testar lançadores no editor de menu integrado.
- Mover aplicativos entre categorias ou adicioná-los a mais de uma categoria.
- Ajustar dimensões do menu, tamanhos dos ícones e posição da barra lateral.
- Pesquisar aplicativos, arquivos, emojis e conteúdo da web, conforme as opções ativadas.
- Fazer contas como `2+3*4`, `sqrt(16)` e `sin(PI/2)` diretamente na pesquisa.
- Usar a aba **Ferramentas** para revisar problemas, restaurar backups,
  importar e exportar perfis ou conferir uma prévia da aparência.

A calculadora aceita operações e funções matemáticas específicas. Os ângulos
são expressos em radianos; o texto digitado não é executado como JavaScript.

## Instalação

O Canellia é um applet para o ambiente de trabalho **Cinnamon**. Na pasta do
projeto, execute o comando abaixo em uma sessão Cinnamon:

```sh
bash install.sh --local --force
```

O instalador precisa de Python 3.8 ou superior e do comando `flock`. Os recursos
do menu e do editor usam os componentes do Cinnamon, GTK e PyGObject. A versão
5.7.0 foi validada em Cinnamon 6.6.9, com X11.

Esse comando também atualiza uma instalação existente. O instalador verifica
os arquivos antes da substituição e restaura a instalação anterior se a
ativação falhar. Se o applet ainda não estiver no painel, abra **Applets** nas
configurações do Cinnamon e adicione **Canellia**.

## Organize seu menu

Abra as configurações do Canellia e entre na primeira aba, **Editor de menu**.
Escolha uma categoria ou procure um aplicativo para editar suas propriedades.

As alterações ficam pendentes até você clicar em **Aplicar**. Use **Desfazer**,
**Refazer** ou **Descartar** enquanto organiza os itens. A aplicação das mudanças
cria backups, disponíveis na aba **Ferramentas**.

Ocultar ou remover um item do menu não desinstala o aplicativo. Lançadores do
sistema ocultos continuam disponíveis pelo filtro **Ocultos** para restauração.
O diagnóstico apresenta problemas para revisão, sem excluir aplicativos
automaticamente.

## Atalhos úteis

| Atalho | Ação |
| --- | --- |
| `Ctrl+F` | Focar a pesquisa do menu |
| `Enter` | Abrir o item selecionado |
| Setas | Navegar entre os itens |
| `Tab` / `Shift+Tab` | Navegar entre aplicativos, categorias e barra lateral |
| `Ctrl+Enter` / tecla Menu | Abrir o menu de contexto |
| `Ctrl+PageUp` / `Ctrl+PageDown` | Trocar páginas de aplicativos |
| `Esc` | Fechar o menu de contexto ou o menu principal |

## Ajude a melhorar

Encontrou um problema ou tem uma ideia? Abra uma
[issue no GitHub](https://github.com/yuri-schmaltz/Canellia/issues).
Conte o que aconteceu, como reproduzir e quais versões do Cinnamon e do
Canellia você utiliza. Capturas ajudam; confira se não mostram dados pessoais.

Para trabalhar no código, veja o [guia de desenvolvimento](DEVELOPMENT.md).
O [relatório de validação](VALIDACAO-5.7.0.md) registra os cenários verificados
e os limites da versão atual. Resultados locais de testes não são versionados.

O identificador técnico do applet é `Canellia@json`.
