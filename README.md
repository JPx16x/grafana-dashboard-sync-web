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
