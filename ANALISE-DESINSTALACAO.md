# Análise da desinstalação pelo menu

## Diagnóstico

A ação Desinstalar usa o caminho do lançador ativo, não uma identidade de
instalação resolvida pelo Canellia. Isso torna lançadores personalizados um
ponto de falha: a cópia local pode representar um aplicativo instalado, mas
não pertencer ao pacote que instalou o aplicativo.

### Cinnamon 5.8 ou posterior

`Canellia@json/5.8/contextmenu.js:333` chama o programa externo
`cinnamon-remove-application` com `app.get_app_info().get_filename()`.
`applet.js:74` verifica somente se esse programa existe. O Canellia não verifica
o pacote, o ID Flatpak ou o escopo de instalação antes de delegar a remoção.

O programa externo não está disponível neste ambiente de execução. Portanto,
não foi possível confirmar sua implementação instalada nem reproduzir o
diálogo dessa versão. Não se deve atribuir automaticamente a ele todos os
defeitos do helper antigo.

### Implementação 4.0

`Canellia@json/4.0/contextmenu.js:314` chama o helper incluído no projeto.
Em `mint-remove-application.py:24`, ele procura o proprietário do caminho com
`dpkg -S`. Se não encontrar, tenta Flatpak; se a tentativa retornar falso,
oferece remover o lançador.

Há três problemas comprovados pelo código:

1. Uma cópia em `~/.local/share/applications` não identifica o pacote Debian
   do lançador original. O helper não procura o original nem resolve outra
   identidade de instalação.
2. Flatpak é reconhecido apenas pela palavra `flatpak` no caminho (linha 58).
   O campo `X-Flatpak` não é lido. Assim, um lançador local com esse campo pode
   ser classificado como não associado a pacote.
3. Ausência de `mintinstall-remove-app` ou qualquer retorno diferente de zero
   leva ao mesmo resultado: oferta de remover o lançador. O fluxo não distingue
   falha, cancelamento e aplicativo não identificado.

O helper ainda tenta excluir tanto o caminho recebido quanto esse caminho
acrescido de `.desktop` (linhas 42–43), sem relação comprovada entre os arquivos.

## Relação com o editor

`Canellia@json/5.8/menuEditorCore.py:518` determina o destino das personalizações:
para um lançador de sistema, grava uma cópia em `data_home/applications/app.id`.
Editar propriedades e alterar visibilidade podem criar essa cópia. Isso é
necessário para personalizar o menu sem escrever nos arquivos de sistema,
mas o desinstalador precisa resolver a instalação além do caminho dessa cópia.

`menuEditorTree.py` já conhece cópias de sistema e normaliza IDs terminados em
`.desktop:flatpak`; essa informação não chega à ação Desinstalar.

## Evidência local e limites

A inspeção somente de leitura encontrou 12 lançadores locais com `X-Flatpak`,
dos quais 7 não têm `flatpak` no caminho. Exemplos: `cc.arduino.IDE2.desktop`,
`org.godotengine.Godot.desktop` e `org.freecad.FreeCAD.desktop`.
Todos esses sete seriam rejeitados pelo teste de caminho do helper 4.0.
O lançador local do Brave contém `Exec=/usr/bin/brave-browser-stable %U`,
outro exemplo de cópia local que aponta para um executável de sistema.

Esses arquivos comprovam a existência dos casos problemáticos, mas não
comprovam que as respectivas instalações ainda existem. Este ambiente não
dispõe dos comandos `dpkg`, `flatpak` e `cinnamon-remove-application` no PATH.
Nenhum aplicativo foi desinstalado e nenhum lançador foi removido ou alterado.

## Correção recomendada

Unificar a resolução da instalação entre as duas versões antes de abrir o
diálogo de remoção:

- Para Flatpak, ler `X-Flatpak`, confirmar o ID instalado e resolver o escopo
  de usuário, sistema ou instalação nomeada. Não inferir a instalação pelo nome
  do arquivo nem pelo nome exibido do aplicativo.
- Para pacotes nativos, consultar o lançador original correspondente ao ID
  nos diretórios de dados e confirmar seu proprietário. Se o `Exec` local tiver
  sido alterado para outro aplicativo, tratar a associação como ambígua em vez
  de remover automaticamente o pacote do original.
- Distinguir instalação identificada, instalação ausente, mecanismo indisponível,
  erro e cancelamento. Falha ou cancelamento não deve virar oferta de excluir
  o lançador como se o aplicativo não estivesse instalado.
- Manter a remoção do lançador como ação separada, com confirmação explícita,
  restrita ao arquivo correspondente ou à ocultação local do item de sistema.

Antes de liberar uma correção, validar lançadores originais e personalizados
de pacotes nativos, Flatpaks de usuário e sistema, IDs de lançadores auxiliares
que diferem do ID do aplicativo, cancelamento, erro, mecanismo ausente e
lançadores sem instalação gerenciada. Os testes não devem desinstalar
aplicativos reais; a integração final precisa ser conferida numa sessão Cinnamon.

## Correção implementada

### Verificação posterior no sistema hospedeiro

O ambiente do terminal é o runtime Flatpak do VS Code. Usando
`flatpak-spawn --host`, foi confirmado que `/usr/bin/cinnamon-remove-application`
existe, é executável e pertence a `mint-common`, versão `2.5.1`, com estado
`install ok installed`. Portanto, a ausência mencionada acima se restringia
ao ambiente isolado; não era ausência no sistema que executa o Cinnamon.
Não foi necessário instalar nem reinstalar o pacote.

A leitura do programa instalado confirmou que ele usa `dpkg -S` no caminho
recebido e reconhece Flatpak pela palavra `flatpak` nesse caminho. Ele também
trata retorno não zero de `mint-remove-flatpak` como motivo para oferecer
remoção do lançador. Isso confirma a relevância da resolução anterior à
delegação e do fluxo próprio para Flatpaks. O diálogo de remoção não foi aberto.

Na atualização do applet, a consulta no sistema hospedeiro revelou que
`flatpak list --columns=ref,installation` retorna referências no formato
`ID/arquitetura/branch`, sem `app/`. O resolver foi corrigido para aceitar
ambos os formatos, com regressão para o formato observado. A consulta real
identificou Brave como pacote `brave-browser` pelo lançador original e
Godot, FreeCAD e Arduino IDE2 como Flatpaks na instalação de sistema.
A instalação do applet e sua recarga pelo D-Bus foram executadas com sucesso.
Essas verificações não executaram desinstalações.

As duas versões agora usam `uninstallApplication.py` e `uninstallCore.py`.
O helper antigo virou um ponto de entrada de compatibilidade. A identificação
consulta `X-Flatpak` e os refs instalados, preservando arquitetura, branch e
escopo; instalações múltiplas são apresentadas para escolha explícita.
A seleção de escopo segue a [referência oficial do Flatpak](https://docs.flatpak.org/en/latest/flatpak-command-reference.html).

Pacotes nativos são resolvidos pelo proprietário confirmado no `dpkg-query`,
incluindo nomes com arquitetura e verificação de estado instalado. Para cópias
locais, o ID do lançador é usado para localizar o original nos diretórios XDG.
Comandos diferentes tornam a associação ambígua e interrompem a remoção.
A confirmação e a resolução de dependências nativas continuam a cargo de
`cinnamon-remove-application`; sua ausência é relatada como indisponibilidade.

Não existe mais exclusão de arquivos como consequência da ação Desinstalar.
Quando nenhuma instalação é encontrada, o diálogo orienta usar a ação separada
no editor. Falhas de consulta e remoção apresentam erro, sem esse redirecionamento.
A confirmação pode ser cancelada sem executar a remoção. A remoção Flatpak
roda fora da thread GTK e comunica falhas, preservando lançadores personalizados.

`tests/test_uninstall.py` cobre identificação, usuário/sistema/instalação nomeada,
lançador auxiliar, branch/arquitetura, cópia local nativa, proprietário com
arquitetura, comando alterado, instalação ausente, erro, cancelamento e
preservação dos arquivos. A validação completa do repositório passou.
A execução real numa sessão Cinnamon ainda precisa ser verificada; não foi
realizada nenhuma desinstalação de aplicativo do usuário durante os testes.
