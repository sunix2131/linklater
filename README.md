# Later

Later хранит ссылки и возвращает их в назначенное время. Можно отложить статью до вечера, курс до выходных или сохранить ссылку без напоминания.

Это desktop-приложение без аккаунта и backend-сервера. Ссылки, заметки, теги и история действий лежат в локальной SQLite базе.

## Возможности

- добавление URL вручную, из буфера обмена и через drag-and-drop;
- напоминания по готовому preset или на выбранную дату;
- разделы для наступивших напоминаний, очереди и архива;
- перенос, завершение, архивирование, удаление и восстановление ссылок;
- поиск по заголовку, заметке, домену и URL;
- фоновая загрузка title, description и favicon;
- импорт и экспорт ZIP, отдельный экспорт CSV;
- светлая, тёмная и системная темы;
- системные уведомления, пока приложение запущено или находится в трее.

URL сохраняется в двух формах. `original_url` нужен для открытия ссылки без изменений. `normalized_url` используется для поиска дубликатов: fragment и известные tracking-параметры удаляются, query-параметры сортируются.

## Локальный запуск

Нужен Python 3.12 или новее.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
python main.py
```

## Проверки

```bash
python -m pytest
python -m ruff check .
python -m mypy src/later
```

Тесты используют временные SQLite базы. Они проверяют нормализацию URL, расчёт дат, переходы между состояниями, FTS fallback, ZIP import/export и обработку повторяющихся ссылок.

## Хранение и перенос данных

Путь к базе зависит от операционной системы и показывается в настройках приложения. Там же можно открыть папку данных.

ZIP export содержит manifest и JSON-файлы таблиц. Import принимает только формат `later-export` версии 1, проверяет имена и структуру файлов и ограничивает распакованный размер архива. Неизвестные файлы и поля отклоняются до записи в базу.

Метаданные загружаются напрямую с сохранённого сайта. Тело страницы ограничено первыми 2 MiB, favicon сохраняется только для того же домена и ограничен 1 MiB. Локальные и сетевые URL по умолчанию запрещены; их можно разрешить в настройках.

## Структура

```text
src/later/
  database.py        SQLite schema, migrations, FTS5 and repositories
  domain.py          link and reminder states
  url_service.py     URL validation and normalization
  scheduling.py      reminder date calculation
  metadata.py        page metadata and favicon loading
  import_export.py   ZIP and CSV formats
  presentation/      PySide6 interface and background workers
tests/
docs/
packaging/
```

## Сборка приложения

В `packaging/pyside6-deploy.spec` лежит конфигурация `pyside6-deploy`. Native package собирается на целевой операционной системе:

```bash
pyside6-deploy -c packaging/pyside6-deploy.spec
```

## Ограничения

- синхронизации между устройствами нет;
- browser extension пока нет;
- полный текст страниц не сохраняется;
- уведомления не работают после полного завершения приложения;
- без FTS5 поиск переключается на SQLite `LIKE`.

Проект распространяется по лицензии MIT. Текст лицензии находится в [LICENSE](LICENSE).
