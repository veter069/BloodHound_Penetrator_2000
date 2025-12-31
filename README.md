Чтобы руками не выполнять различные запросы для поиска недостатков в инфраструктуре на базе Active Directory создан скрипт generator.py, который преобразует результаты Cypher запросов из BloodHound в структурированные задачи для чек-листа Obsidian, позволяя автоматизировать процесс аудита безопасности Active Directory и отслеживать прогресс исправления уязвимостей.

Погроммирую под связку Ubuntu + BloodHound в Docker. Креды в .env.

# 1) Подключение к Neo4j в Docker (Ubuntu)
Если Neo4j запущен в compose, у него должен быть открыт Bolt:
- bolt://localhost:7687 (если порт проброшен наружу)
- либо bolt://neo4j:7687 (если скрипт тоже запускается внутри того же docker network)

Проверь:
```bash
docker ps
docker port <container_id_or_name> 7687
```

# 2) Установка зависимостей (на хосте Ubuntu)
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install neo4j jinja2 python-dotenv
```

# 3) Структура проекта (как удобно держать рядом с Obsidian)
```bash
BloodHound_Penetrator_2000/
  generator.py
  queries.json
  ownedqueries.json
  .env
  output/
```

.env пример:
```bash
NEO4J_URI=bolt://127.0.0.1:7687
NEO4J_USER=neo4j
NEO4J_PASS=your_password
OBSIDIAN_OUT=./output
VAULT_LINK_PREFIX=
```
