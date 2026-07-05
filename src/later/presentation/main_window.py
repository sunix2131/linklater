from __future__ import annotations

import platform
import webbrowser
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QDateTime, QObject, QRunnable, Qt, QThreadPool, QTimer, Signal, Slot
from PySide6.QtGui import QAction, QCloseEvent, QGuiApplication
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QDateTimeEdit,
    QDialog,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QStackedWidget,
    QSystemTrayIcon,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from later import __version__
from later.database import LinkRepository
from later.domain import Link, LinkMetadata, LinkStatus, ReminderPreset
from later.import_export import ImportExportService
from later.metadata import MetadataClient
from later.paths import AppPaths
from later.scheduling import SchedulingService
from later.url_service import UrlError, UrlNormalizationService

RU = {
    "today": "На сегодня",
    "queue": "Очередь",
    "archive": "Архив",
    "search": "Поиск",
    "settings": "Настройки",
}

STATUS_LABELS = {
    LinkStatus.SCHEDULED: "Запланировано",
    LinkStatus.DUE: "Пора вернуться",
    LinkStatus.COMPLETED: "Прочитано",
    LinkStatus.ARCHIVED: "В архиве",
    LinkStatus.DELETED: "В корзине",
}


class MetadataSignals(QObject):
    loaded = Signal(str, object)


class MetadataTask(QRunnable):
    def __init__(
        self, link_id: str, client: MetadataClient, url: str, normalized: str, domain: str, fetch_favicon: bool
    ) -> None:
        super().__init__()
        self.link_id = link_id
        self.client = client
        self.url = url
        self.normalized = normalized
        self.domain = domain
        self.fetch_favicon = fetch_favicon
        self.signals = MetadataSignals()

    @Slot()
    def run(self) -> None:
        self.signals.loaded.emit(
            self.link_id,
            self.client.fetch(self.url, self.normalized, self.domain, fetch_favicon=self.fetch_favicon),
        )


class AddLinkDialog(QDialog):
    def __init__(self, parent: QWidget, settings_time: str) -> None:
        super().__init__(parent)
        self.setWindowTitle("Добавить ссылку")
        self.resize(640, 560)
        self.url = QLineEdit()
        self.url.setPlaceholderText("https://example.com/article")
        self.title = QLineEdit()
        self.title.setPlaceholderText("Можно оставить пустым, Later попробует заполнить сам")
        self.description = QTextEdit()
        self.description.setPlaceholderText("Короткое описание страницы")
        self.description.setFixedHeight(70)
        self.note = QTextEdit()
        self.note.setPlaceholderText("Зачем ты сохранил эту ссылку?")
        self.note.setFixedHeight(70)
        self.tags = QLineEdit()
        self.tags.setPlaceholderText("работа, купить, прочитать")
        self.preset = QComboBox()
        self.preset.addItems(
            [
                "Сегодня вечером",
                "Завтра",
                "Через 3 дня",
                "В выходные",
                "Через неделю",
                "Через месяц",
                "Выбрать дату и время",
                "Сохранить без напоминания",
            ]
        )
        self.custom_dt = QDateTimeEdit(QDateTime.currentDateTime())
        self.custom_dt.setCalendarPopup(True)
        self.custom_dt.setEnabled(False)
        self.preset.currentIndexChanged.connect(lambda idx: self.custom_dt.setEnabled(idx == 6))
        paste = QPushButton("Вставить из буфера")
        paste.setObjectName("secondaryButton")
        paste.clicked.connect(self._paste)
        save = QPushButton("Сохранить")
        save.setObjectName("primaryButton")
        save.setDefault(True)
        save.clicked.connect(self.accept)
        cancel = QPushButton("Отмена")
        cancel.setObjectName("ghostButton")
        cancel.clicked.connect(self.reject)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        form.setHorizontalSpacing(16)
        form.setVerticalSpacing(12)
        form.addRow("URL", self.url)
        form.addRow("", paste)
        form.addRow("Заголовок", self.title)
        form.addRow("Описание", self.description)
        form.addRow("Личная заметка", self.note)
        form.addRow("Теги", self.tags)
        form.addRow("Когда показать снова", self.preset)
        form.addRow("Дата и время", self.custom_dt)
        buttons = QHBoxLayout()
        buttons.addStretch()
        buttons.addWidget(cancel)
        buttons.addWidget(save)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 22)
        title = QLabel("<h2>Сохранить ссылку</h2><p>Выбери момент, когда Later должен вернуть её обратно.</p>")
        title.setObjectName("dialogHeader")
        layout.addWidget(title)
        layout.addLayout(form)
        layout.addLayout(buttons)

    def _paste(self) -> None:
        self.url.setText(QGuiApplication.clipboard().text().strip())

    def selected_preset(self) -> ReminderPreset:
        return [
            ReminderPreset.TONIGHT,
            ReminderPreset.TOMORROW,
            ReminderPreset.THREE_DAYS,
            ReminderPreset.WEEKEND,
            ReminderPreset.WEEK,
            ReminderPreset.MONTH,
            ReminderPreset.CUSTOM,
            ReminderPreset.NONE,
        ][self.preset.currentIndex()]

    def tag_values(self) -> list[str]:
        return [tag.strip() for tag in self.tags.text().split(",") if tag.strip()]


class MainWindow(QMainWindow):
    def __init__(self, repo: LinkRepository, paths: AppPaths) -> None:
        super().__init__()
        self.repo = repo
        self.paths = paths
        self.settings = repo.settings()
        self.url_service = UrlNormalizationService()
        self.scheduler = SchedulingService()
        self.io = ImportExportService(repo)
        self.pool = QThreadPool.globalInstance()
        self.show_more_count = self.settings.daily_limit
        self.setWindowTitle("Later")
        self.setMinimumSize(1000, 680)
        self.resize(1180, 760)
        self._build_ui()
        self._build_tray()
        self._apply_theme()
        self._refresh_all()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(60_000)
        self._tick()

    def _build_ui(self) -> None:
        self.nav = QListWidget()
        self.nav.setObjectName("sidebarNav")
        self.nav.setFixedWidth(220)
        for key in ("today", "queue", "archive", "search", "settings"):
            QListWidgetItem(RU[key], self.nav)
        self.nav.currentRowChanged.connect(self._switch_page)
        add_button = QPushButton("Добавить ссылку")
        add_button.setObjectName("primaryButton")
        add_button.setToolTip("Добавить новую ссылку. Горячая клавиша Ctrl/Cmd+N")
        add_button.clicked.connect(self.add_link)
        self.active_label = QLabel()
        self.active_label.setObjectName("sidebarMetric")
        self.version_label = QLabel(f"Later {__version__}")
        self.version_label.setObjectName("mutedLabel")
        sidebar = QVBoxLayout()
        sidebar.setContentsMargins(18, 18, 18, 18)
        sidebar.setSpacing(12)
        brand = QLabel("<h1>Later</h1><p>Сохрани сейчас, открой вовремя</p>")
        brand.setObjectName("brand")
        sidebar.addWidget(brand)
        sidebar.addWidget(self.nav)
        sidebar.addStretch()
        sidebar.addWidget(self.active_label)
        sidebar.addWidget(add_button)
        sidebar.addWidget(self.version_label)

        self.stack = QStackedWidget()
        self.today_table = self._table()
        self.queue_table = self._table()
        self.archive_table = self._table()
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Поиск по названию, заметке, домену или URL")
        self.search_input.textChanged.connect(self._search)
        self.search_status = QComboBox()
        self.search_status.addItems(["all", "scheduled", "due", "completed", "archived", "deleted"])
        self.search_status.currentTextChanged.connect(self._search)
        self.search_table = self._table()
        self.today_count = QLabel()
        self.queue_count = QLabel()
        self.archive_count = QLabel()
        self.search_count = QLabel()

        self.stack.addWidget(
            self._page(
                "Ссылки, которые пора открыть",
                "Later хранит не просто закладки: он возвращает сохранённые ссылки в выбранный день.",
                self.today_table,
                self._today_top_area(),
                self.today_count,
            )
        )
        self.stack.addWidget(
            self._page(
                "Очередь",
                "Будущие напоминания и ссылки, которые ещё ждут своего часа.",
                self.queue_table,
                badge=self.queue_count,
            )
        )
        self.stack.addWidget(
            self._page(
                "Архив",
                "Прочитанные, архивированные и удалённые ссылки в одном месте.",
                self.archive_table,
                badge=self.archive_count,
            )
        )
        search_controls = QHBoxLayout()
        search_controls.setContentsMargins(0, 0, 0, 0)
        search_controls.setSpacing(10)
        search_controls.addWidget(self.search_input)
        search_controls.addWidget(self.search_status)
        search_box = QWidget()
        search_box.setLayout(search_controls)
        self.stack.addWidget(
            self._page(
                "Поиск",
                "Найди старую ссылку по словам, домену, заметке или URL.",
                self.search_table,
                search_box,
                self.search_count,
            )
        )
        self.stack.addWidget(self._settings_page())

        root = QHBoxLayout()
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        side = QWidget()
        side.setObjectName("sidebar")
        side.setLayout(sidebar)
        root.addWidget(side)
        root.addWidget(self.stack, 1)
        central = QWidget()
        central.setLayout(root)
        self.setCentralWidget(central)
        self.nav.setCurrentRow(0)

        new_action = QAction("Добавить ссылку", self)
        new_action.setShortcut("Meta+N" if platform.system() == "Darwin" else "Ctrl+N")
        new_action.triggered.connect(self.add_link)
        self.addAction(new_action)
        self.setAcceptDrops(True)

    def _table(self) -> QTableWidget:
        table = QTableWidget(0, 8)
        table.setHorizontalHeaderLabels(
            ["Название", "Домен", "Заметка", "Теги", "Статус", "Дата", "Переносы", "Действия"]
        )
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(6, QHeaderView.ResizeMode.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(7, QHeaderView.ResizeMode.ResizeToContents)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setAlternatingRowColors(False)
        table.setWordWrap(True)
        table.setShowGrid(False)
        table.verticalHeader().setVisible(False)
        table.verticalHeader().setDefaultSectionSize(78)
        return table

    def _page(
        self,
        title: str,
        subtitle: str,
        table: QTableWidget,
        extra: QWidget | None = None,
        badge: QLabel | None = None,
    ) -> QWidget:
        page = QWidget()
        page.setObjectName("page")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(16)
        header = QFrame()
        header.setObjectName("pageHeader")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(18, 16, 18, 16)
        copy = QLabel(f"<h1>{title}</h1><p>{subtitle}</p>")
        copy.setObjectName("pageTitle")
        header_layout.addWidget(copy, 1)
        if badge is not None:
            badge.setObjectName("countBadge")
            header_layout.addWidget(badge)
        layout.addWidget(header)
        if extra:
            layout.addWidget(extra)
        layout.addWidget(table, 1)
        return page

    def _today_buttons(self) -> QWidget:
        show_more = QPushButton("Показать ещё")
        show_more.setObjectName("secondaryButton")
        show_more.clicked.connect(self._show_more)
        box = QWidget()
        layout = QHBoxLayout(box)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addStretch()
        layout.addWidget(show_more)
        return box

    def _today_top_area(self) -> QWidget:
        area = QWidget()
        layout = QVBoxLayout(area)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        layout.addWidget(self._purpose_panel())
        layout.addWidget(self._today_buttons())
        return area

    def _purpose_panel(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("purposePanel")
        layout = QHBoxLayout(panel)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(14)
        steps = [
            ("1", "Сохрани ссылку", "Статья, видео, товар, курс или вакансия."),
            ("2", "Выбери момент", "Сегодня вечером, завтра, через неделю или без срока."),
            ("3", "Вернись вовремя", "Когда срок наступит, ссылка появится здесь."),
        ]
        for number, title, text in steps:
            layout.addWidget(self._purpose_step(number, title, text), 1)
        return panel

    def _purpose_step(self, number: str, title: str, text: str) -> QWidget:
        step = QFrame()
        step.setObjectName("purposeStep")
        layout = QHBoxLayout(step)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(10)
        badge = QLabel(number)
        badge.setObjectName("stepBadge")
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        copy = QLabel(f"<b>{title}</b><br><span>{text}</span>")
        copy.setObjectName("stepCopy")
        copy.setWordWrap(True)
        layout.addWidget(badge)
        layout.addWidget(copy, 1)
        return step

    def _settings_page(self) -> QWidget:
        page = QWidget()
        page.setObjectName("page")
        outer = QVBoxLayout(page)
        outer.setContentsMargins(28, 24, 28, 24)
        outer.setSpacing(16)
        header = QFrame()
        header.setObjectName("pageHeader")
        header_layout = QVBoxLayout(header)
        header_layout.setContentsMargins(18, 16, 18, 16)
        header_layout.addWidget(QLabel("<h1>Настройки</h1><p>Поведение, приватность, данные и диагностика Later.</p>"))
        outer.addWidget(header)
        layout = QFormLayout()
        layout.setHorizontalSpacing(18)
        layout.setVerticalSpacing(12)
        self.language = QComboBox()
        self.language.addItems(["ru", "en"])
        self.language.setCurrentText(self.settings.language)
        self.theme = QComboBox()
        self.theme.addItems(["system", "light", "dark"])
        self.theme.setCurrentText(self.settings.theme)
        self.daily_limit = QSpinBox()
        self.daily_limit.setRange(0, 10)
        self.daily_limit.setSpecialValueText("без лимита")
        self.daily_limit.setValue(self.settings.daily_limit)
        self.delivery_time = QLineEdit(self.settings.default_delivery_time)
        self.local_urls = QCheckBox()
        self.local_urls.setChecked(self.settings.allow_local_network_urls)
        self.favicons = QCheckBox()
        self.favicons.setChecked(self.settings.fetch_favicons)
        save = QPushButton("Сохранить настройки")
        save.setObjectName("primaryButton")
        save.clicked.connect(self._save_settings)
        export_zip = QPushButton("Экспорт ZIP")
        export_zip.setObjectName("secondaryButton")
        export_zip.clicked.connect(self._export_zip)
        export_csv = QPushButton("Экспорт CSV")
        export_csv.setObjectName("secondaryButton")
        export_csv.clicked.connect(self._export_csv)
        import_zip = QPushButton("Импорт ZIP")
        import_zip.setObjectName("secondaryButton")
        import_zip.clicked.connect(self._import_zip)
        open_data = QPushButton("Открыть папку данных")
        open_data.setObjectName("secondaryButton")
        open_data.clicked.connect(lambda: webbrowser.open(self.paths.data_dir.as_uri()))
        purge = QPushButton("Очистить старую корзину")
        purge.setObjectName("dangerButton")
        purge.clicked.connect(self._purge)
        layout.addRow("Язык", self.language)
        layout.addRow("Тема", self.theme)
        layout.addRow("Карточек на сегодня", self.daily_limit)
        layout.addRow("Время по умолчанию", self.delivery_time)
        layout.addRow("Разрешить локальные URL", self.local_urls)
        layout.addRow("Загружать favicon", self.favicons)
        layout.addRow(save)
        layout.addRow(export_zip, export_csv)
        layout.addRow(import_zip, open_data)
        layout.addRow(purge)
        layout.addRow("Версия Python", QLabel(platform.python_version()))
        layout.addRow("Статус FTS5", QLabel("включён" if self.repo.db.fts_enabled else "LIKE fallback"))
        layout.addRow("Путь базы данных", QLabel(str(self.paths.db_path)))
        layout.addRow("Путь cache directory", QLabel(str(self.paths.cache_dir)))
        group = QGroupBox("Параметры приложения")
        group.setLayout(layout)
        outer.addWidget(group)
        outer.addStretch()
        return page

    def _build_tray(self) -> None:
        self.tray = QSystemTrayIcon(self)
        self.tray.setToolTip("Later")
        menu = QMenu()
        menu.addAction("Открыть Later", self.showNormal)
        menu.addAction("Показать ссылки на сегодня", lambda: self.nav.setCurrentRow(0))
        menu.addAction("Добавить ссылку", self.add_link)
        menu.addAction("Настройки", lambda: self.nav.setCurrentRow(4))
        menu.addAction("Завершить приложение", QApplication.quit)
        self.tray.setContextMenu(menu)
        if QSystemTrayIcon.isSystemTrayAvailable() and self.settings.tray_enabled:
            self.tray.show()

    def add_link(self, initial_url: str = "") -> None:
        dialog = AddLinkDialog(self, self.settings.default_delivery_time)
        if initial_url:
            dialog.url.setText(initial_url)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            normalized = self.url_service.normalize(
                dialog.url.text(), allow_local=self.settings.allow_local_network_urls
            )
            preset = dialog.selected_preset()
            scheduled: datetime | None
            if preset is ReminderPreset.CUSTOM:
                custom_value = dialog.custom_dt.dateTime().toPython()
                if not isinstance(custom_value, datetime):
                    QMessageBox.warning(self, "Later", "Не удалось прочитать выбранную дату.")
                    return
                scheduled = custom_value.astimezone()
            else:
                scheduled = self.scheduler.preset_time(
                    preset,
                    default_delivery_time=self.settings.default_delivery_time,
                )
            link = self.repo.add_link(
                original_url=normalized.original,
                normalized_url=normalized.normalized,
                domain=normalized.domain,
                title=dialog.title.text() or normalized.domain,
                description=dialog.description.toPlainText(),
                note=dialog.note.toPlainText(),
                tags=dialog.tag_values(),
                scheduled_at_utc=scheduled,
                timezone_name=str(datetime.now().astimezone().tzinfo),
                preset=preset,
            )
        except UrlError as exc:
            QMessageBox.warning(self, "Later", str(exc))
            return
        except ValueError as exc:
            if str(exc).startswith("duplicate:"):
                QMessageBox.information(
                    self, "Later", "Эта ссылка уже сохранена. Откройте существующую запись через поиск."
                )
                return
            QMessageBox.warning(self, "Later", str(exc))
            return
        self._start_metadata(link)
        self._refresh_all()

    def _start_metadata(self, link: Link) -> None:
        client = MetadataClient(self.paths.favicons_dir, self.settings.metadata_timeout_seconds)
        task = MetadataTask(
            link.id, client, link.original_url, link.normalized_url, link.domain, self.settings.fetch_favicons
        )
        task.signals.loaded.connect(self._metadata_loaded)
        self.pool.start(task)

    def _metadata_loaded(self, link_id: str, metadata: LinkMetadata) -> None:
        self.repo.update_metadata(link_id, metadata.title, metadata.description, metadata.favicon_path)
        self._refresh_all()

    def _populate(self, table: QTableWidget, links: list[Link], empty_title: str, empty_subtitle: str) -> None:
        if not links:
            table.setRowCount(1)
            table.setSpan(0, 0, 1, table.columnCount())
            item = QTableWidgetItem(f"{empty_title}\n{empty_subtitle}")
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsSelectable)
            table.setItem(0, 0, item)
            table.setRowHeight(0, 170)
            return
        table.clearSpans()
        table.setRowCount(len(links))
        for row, link in enumerate(links):
            table.setRowHeight(row, 82)
            date = link.scheduled_at_utc or link.completed_at or link.archived_at or link.deleted_at or link.created_at
            values = [
                link.title or link.domain,
                link.domain,
                link.note,
                self._format_tags(link),
                STATUS_LABELS[link.status],
                date.astimezone().strftime("%Y-%m-%d %H:%M") if date else "",
                str(link.postpone_count),
            ]
            for col, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setToolTip(value)
                if col == 4:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                table.setItem(row, col, item)
            actions = QWidget()
            layout = QHBoxLayout(actions)
            layout.setContentsMargins(6, 6, 6, 6)
            layout.setSpacing(6)
            for label, action in self._actions_for(link):
                button = QPushButton(label)
                button.setObjectName(self._button_style(action))
                button.setToolTip(self._action_hint(action))
                button.clicked.connect(lambda _=False, lid=link.id, act=action: self._link_action(lid, act))
                layout.addWidget(button)
            table.setCellWidget(row, 7, actions)

    def _actions_for(self, link: Link) -> list[tuple[str, str]]:
        base = [("Открыть", "open")]
        if link.status in {LinkStatus.DUE, LinkStatus.SCHEDULED}:
            base += [("Прочитал", "complete"), ("Отложить", "postpone"), ("Архив", "archive"), ("Удалить", "delete")]
        elif link.status is LinkStatus.DELETED:
            base += [("Восстановить", "restore")]
        return base

    def _format_tags(self, link: Link) -> str:
        return " ".join(f"#{tag}" for tag in link.tags) if link.tags else "без тегов"

    def _button_style(self, action: str) -> str:
        if action == "open":
            return "primaryButton"
        if action == "delete":
            return "dangerButton"
        return "secondaryButton"

    def _action_hint(self, action: str) -> str:
        return {
            "open": "Открыть ссылку в браузере по умолчанию",
            "complete": "Отметить ссылку прочитанной",
            "postpone": "Перенести напоминание на завтра",
            "archive": "Сохранить без активного напоминания",
            "delete": "Переместить ссылку в корзину",
            "restore": "Вернуть ссылку из корзины в архив",
        }.get(action, "")

    def _link_action(self, link_id: str, action: str) -> None:
        if action == "open":
            link = self.repo.get(link_id)
            if webbrowser.open(link.original_url):
                self.repo.action(link_id, "open")
            else:
                QMessageBox.warning(self, "Later", "Не удалось открыть браузер.")
        elif action == "postpone":
            scheduled = self.scheduler.preset_time(
                ReminderPreset.TOMORROW, default_delivery_time=self.settings.default_delivery_time
            )
            self.repo.action(link_id, "postpone", scheduled, ReminderPreset.TOMORROW.value)
        else:
            self.repo.action(link_id, action)
        self._refresh_all()

    def _refresh_all(self) -> None:
        limit = self.show_more_count or None
        today = self.repo.today(limit)
        all_today = self.repo.today(None)
        queue = self.repo.queue()
        archive = self.repo.archive()
        self._populate(
            self.today_table,
            today,
            "На сегодня ничего не запланировано",
            "Сохрани ссылку и попроси Later вернуть её в удобный момент.",
        )
        self._populate(
            self.queue_table,
            queue,
            "Очередь пока пустая",
            "Будущие напоминания появятся здесь после добавления ссылок.",
        )
        self._populate(
            self.archive_table,
            archive,
            "Архив пуст",
            "Прочитанные, архивированные и удалённые ссылки будут собираться здесь.",
        )
        active = len(all_today) + len(queue)
        self.active_label.setText(f"Активных: {active}")
        self.today_count.setText(f"{len(all_today)} сегодня")
        self.queue_count.setText(f"{len(queue)} в очереди")
        self.archive_count.setText(f"{len(archive)} в архиве")
        self._search()

    def _search(self) -> None:
        results = self.repo.search(self.search_input.text(), self.search_status.currentText())
        self.search_count.setText(f"{len(results)} найдено")
        self._populate(
            self.search_table,
            results,
            "Введите запрос",
            "Поиск начнётся после двух символов.",
        )

    def _show_more(self) -> None:
        self.show_more_count = (self.show_more_count or 0) + 5
        self._refresh_all()

    def _tick(self) -> None:
        changed = self.repo.resolve_due()
        if changed and self.settings.notifications_enabled:
            message = f"Появились ссылки на сегодня: {changed}"
            if self.tray.isVisible():
                self.tray.showMessage("Later", message)
            else:
                QMessageBox.information(self, "Later", message)
        self._refresh_all()

    def _switch_page(self, index: int) -> None:
        self.stack.setCurrentIndex(index)

    def _save_settings(self) -> None:
        self.settings.language = self.language.currentText()
        self.settings.theme = self.theme.currentText()
        self.settings.daily_limit = self.daily_limit.value()
        self.settings.default_delivery_time = self.delivery_time.text()
        self.settings.allow_local_network_urls = self.local_urls.isChecked()
        self.settings.fetch_favicons = self.favicons.isChecked()
        self.repo.save_settings(self.settings)
        self._apply_theme()
        self._refresh_all()

    def _apply_theme(self) -> None:
        dark = self.settings.theme == "dark"
        self.setStyleSheet(
            """
            QWidget { font-size: 14px; color: #e5e7eb; }
            QMainWindow, #page { background: #111827; }
            #sidebar { background: #172033; border-right: 1px solid #293548; }
            #brand h1 { margin: 0; color: #f9fafb; font-size: 28px; }
            #brand p, #mutedLabel, #dialogHeader p { color: #9ca3af; }
            #sidebarNav { background: transparent; border: 0; outline: 0; }
            #sidebarNav::item { padding: 12px 14px; border-radius: 6px; margin: 2px 0; color: #cbd5e1; }
            #sidebarNav::item:selected { background: #2563eb; color: white; }
            #sidebarMetric, #countBadge {
                background: #243044; border: 1px solid #38455a; border-radius: 6px; padding: 8px 10px;
            }
            #pageHeader {
                background: #172033; border: 1px solid #2a3648; border-radius: 8px;
            }
            #purposePanel {
                background: #101827; border: 1px solid #2a3648; border-radius: 8px;
            }
            #purposeStep {
                background: #172033; border: 1px solid #293548; border-radius: 8px;
            }
            #stepBadge {
                min-width: 30px; max-width: 30px; min-height: 30px; max-height: 30px;
                border-radius: 15px; background: #2563eb; color: white; font-weight: 700;
            }
            #stepCopy b { color: #f9fafb; }
            #stepCopy span { color: #aab4c3; }
            #pageTitle h1 { margin: 0; color: #f9fafb; font-size: 26px; }
            #pageTitle p { color: #aab4c3; }
            QGroupBox { border: 1px solid #2a3648; border-radius: 8px; margin-top: 16px; padding: 16px; }
            QGroupBox::title { color: #e5e7eb; subcontrol-origin: margin; left: 12px; padding: 0 4px; }
            QTableWidget, QTextEdit, QLineEdit, QComboBox, QDateTimeEdit {
                background: #172033; color: #f9fafb; border: 1px solid #374151; padding: 7px; border-radius: 6px;
            }
            QHeaderView::section { background: #111827; color: #9ca3af; border: 0; padding: 9px; }
            QTableWidget { gridline-color: transparent; selection-background-color: #26364f; }
            QTableWidget::item { border-bottom: 1px solid #253044; padding: 8px; }
            QPushButton { border: 0; padding: 8px 11px; border-radius: 6px; }
            #primaryButton { background: #2563eb; color: white; }
            #secondaryButton { background: #253247; color: #e5e7eb; border: 1px solid #3b475c; }
            #ghostButton { background: transparent; color: #cbd5e1; border: 1px solid #3b475c; }
            #dangerButton { background: #7f1d1d; color: white; }
            """
            if dark
            else """
            QWidget { font-size: 14px; color: #111827; }
            QMainWindow, #page { background: #f6f7fb; }
            #sidebar { background: #ffffff; border-right: 1px solid #e5e7eb; }
            #brand h1 { margin: 0; color: #111827; font-size: 28px; }
            #brand p, #mutedLabel, #dialogHeader p { color: #64748b; }
            #sidebarNav { background: transparent; border: 0; outline: 0; }
            #sidebarNav::item { padding: 12px 14px; border-radius: 6px; margin: 2px 0; color: #334155; }
            #sidebarNav::item:selected { background: #e8f0ff; color: #1d4ed8; }
            #sidebarMetric, #countBadge {
                background: #f1f5f9; border: 1px solid #e2e8f0; border-radius: 6px; padding: 8px 10px;
            }
            #pageHeader {
                background: #ffffff; border: 1px solid #e5e7eb; border-radius: 8px;
            }
            #purposePanel {
                background: #ffffff; border: 1px solid #e5e7eb; border-radius: 8px;
            }
            #purposeStep {
                background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px;
            }
            #stepBadge {
                min-width: 30px; max-width: 30px; min-height: 30px; max-height: 30px;
                border-radius: 15px; background: #2563eb; color: white; font-weight: 700;
            }
            #stepCopy b { color: #111827; }
            #stepCopy span { color: #64748b; }
            #pageTitle h1 { margin: 0; color: #111827; font-size: 26px; }
            #pageTitle p { color: #64748b; }
            QGroupBox {
                background: white; border: 1px solid #e5e7eb;
                border-radius: 8px; margin-top: 16px; padding: 16px;
            }
            QGroupBox::title { color: #334155; subcontrol-origin: margin; left: 12px; padding: 0 4px; }
            QTableWidget, QTextEdit, QLineEdit, QComboBox, QDateTimeEdit {
                background: white; border: 1px solid #d7dce5; padding: 7px; border-radius: 6px;
            }
            QHeaderView::section { background: #f6f7fb; color: #64748b; border: 0; padding: 9px; }
            QTableWidget { gridline-color: transparent; selection-background-color: #e8f0ff; }
            QTableWidget::item { border-bottom: 1px solid #eef2f7; padding: 8px; }
            QPushButton { border: 0; padding: 8px 11px; border-radius: 6px; }
            #primaryButton { background: #2563eb; color: white; }
            #secondaryButton { background: #eef2f7; color: #1f2937; border: 1px solid #d7dce5; }
            #ghostButton { background: transparent; color: #334155; border: 1px solid #d7dce5; }
            #dangerButton { background: #dc2626; color: white; }
            """
        )

    def _export_zip(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Экспорт ZIP", str(self.paths.exports_dir / "later-export.zip"), "ZIP (*.zip)"
        )
        if path:
            self.io.export_zip(Path(path))

    def _export_csv(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Экспорт CSV", str(self.paths.exports_dir / "later-links.csv"), "CSV (*.csv)"
        )
        if path:
            self.io.export_csv(Path(path))

    def _import_zip(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Импорт ZIP", str(self.paths.exports_dir), "ZIP (*.zip)")
        if path:
            links, tags = self.io.import_zip(Path(path), "skip")
            QMessageBox.information(self, "Later", f"Импортировано ссылок: {links}, тегов: {tags}")
            self._refresh_all()

    def _purge(self) -> None:
        count = self.repo.purge_deleted()
        QMessageBox.information(self, "Later", f"Удалено навсегда: {count}")
        self._refresh_all()

    def dragEnterEvent(self, event) -> None:  # noqa: N802
        if event.mimeData().hasText():
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:  # noqa: N802
        self.add_link(event.mimeData().text().strip())

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        if self.settings.close_behavior == "tray" and self.tray.isVisible():
            event.ignore()
            self.hide()
        else:
            event.accept()
