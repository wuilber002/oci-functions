# Changelog

[Read this changelog in English](./changelog_en-US.md) <span>&#127482;&#127480;</span>

Este documento registra as mudanças relevantes introduzidas após a versão
inicial publicada do projeto.

## Versão atual — 2026-07-28

### Alterado

- A sincronização passou a comparar os objetos da origem e do destino por seu
  caminho relativo (`Ano/Mês/Dia/arquivo`), preservando a hierarquia no bucket
  de destino.
- A listagem do Object Storage passou a usar a paginação correta da API
  (`next_start_with`/`start`) e a processar os resultados como fluxos, sem
  manter o inventário completo dos buckets em memória.
- A listagem do destino começa no primeiro caminho presente na origem. Isso
  evita percorrer histórico que não pode corresponder aos relatórios atuais e
  impede que o objeto de lock ocupe uma posição útil da página de resultados.
- A igualdade dos arquivos passou a ser determinada por `size` e `md5`. O ETag
  continua sendo usado como pré-condição de segurança durante a cópia, não como
  critério de equivalência entre origem e destino.
- A região do bucket de destino aceita `OCI_BUCKET_DESTINATION_REGION` como
  sobrescrita; na ausência dela, usa `OCI_RESOURCE_PRINCIPAL_REGION`.
- A estratégia de repetição do SDK foi limitada para respeitar o tempo máximo
  de execução da Function.

### Adicionado

- Lock distribuído no bucket de destino, com expiração e ETag, para bloquear
  execuções simultâneas.
- Cópias assíncronas submetidas antes do *polling* dos *work requests*,
  reduzindo consultas repetidas e dando mais tempo ao Object Storage para
  concluir o trabalho.
- Métricas de execução na resposta e no log: objetos de origem e destino,
  cópias, atualizações, iguais, erros, pendências, conflitos e páginas
  consultadas.
- Logs estruturados em JSON para eventos operacionais e diagnóstico detalhado
  de cópias falhas, incluindo erros e logs do *work request*.
- Supressão dos logs HTTP em nível `DEBUG` do `urllib3`, mantendo mensagens de
  aviso e erro relevantes.
- Testes unitários para paginação, merge, comparação de objetos, região de
  destino, lock, cópias e erros de *work request*.
- Procedimentos de atualização da Function em português e inglês.
- Diagramas, fluxo de execução, instruções de teste antes do *deploy* e
  documentação ampliada em português e inglês.

### Corrigido

- Paginação incompleta de `list_objects`, que fazia objetos fora da primeira
  página serem tratados como ausentes.
- Avanço incorreto do merge após encontrar um objeto igual, que podia submeter
  uma cópia indevida com a pré-condição `if-none-match`.
- Falhas de cópia agora expõem a causa retornada pelo Object Storage, em vez de
  registrar somente o status `FAILED`.

### Compatibilidade e operação

- A Function continua usando a mesma Application, OCID, Dynamic Group,
  policies e agendamento quando atualizada pelo procedimento documentado.
- Execute `python -m unittest -v` e `python -m py_compile func.py test_func.py`
  antes de publicar uma nova imagem.

