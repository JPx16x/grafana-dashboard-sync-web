# Grafana Dashboard Sync Web

Aplicação web para sincronizar dashboards entre organizações do Grafana.

A ferramenta permite escolher uma organização modelo, selecionar dashboards, definir o datasource de referência e aplicar a sincronização em uma ou mais organizações destino.

## Recursos

- Login próprio da aplicação.
- Conexão com Grafana via usuário admin.
- Listagem de organizações.
- Seleção da organização origem/modelo.
- Listagem de dashboards da origem.
- Listagem de datasources da origem.
- Seleção de um ou mais datasources de referência.
- Seleção de organizações destino.
- Execução em modo dry-run.
- Sincronização real.
- Backup automático antes de sobrescrever dashboards existentes.
- Logs por execução.
- Serviço systemd com Gunicorn.
- Porta configurável.

## Requisitos

Compatível com:

- Debian
- Ubuntu

Pacotes instalados automaticamente pelo instalador:

- git
- python3
- python3-venv
- python3-pip
- curl

## Instalação rápida

Execute como root ou usando sudo:

```bash
curl -fsSL https://raw.githubusercontent.com/JPx16x/grafana-dashboard-sync-web/main/install.sh | sudo bash


## Replicacao total com datasources

A aplicacao possui uma opcao para criar automaticamente datasources ausentes nas organizacoes destino.

Quando a opcao `Criar datasources ausentes nas organizacoes destino` estiver marcada, a ferramenta faz o seguinte fluxo:

1. Valida os datasources selecionados na organizacao origem.
2. Verifica se cada datasource existe na organizacao destino.
3. Se existir, utiliza o datasource encontrado.
4. Se nao existir, tenta criar o datasource na organizacao destino copiando a configuracao da origem.
5. Apos isso, importa os dashboards selecionados usando os UIDs corretos dos datasources da organizacao destino.

### Observacao sobre credenciais sensiveis

O Grafana nao retorna senhas, tokens e outros campos sensiveis pela API apos o datasource ser criado.

Por isso, alguns datasources podem ser criados com a estrutura correta, mas podem exigir ajuste manual de senha/token depois da criacao.

Exemplos comuns:

- MySQL com senha.
- PostgreSQL com senha.
- MSSQL com senha.
- Zabbix com token ou Basic Auth.

