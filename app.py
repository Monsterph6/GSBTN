from __future__ import annotations

import math
import sys
from pathlib import Path
from typing import Any

from PyQt6.QtCore import QAbstractTableModel, QModelIndex, Qt, QTimer
from PyQt6.QtGui import QAction, QColor, QFont, QIcon
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressDialog,
    QPushButton,
    QSpinBox,
    QSplitter,
    QStackedWidget,
    QTableView,
    QTabWidget,
    QTextEdit,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

try:
    from PyQt6.QtCharts import QBarCategoryAxis, QBarSeries, QBarSet, QChart, QChartView, QValueAxis
    CHARTS_AVAILABLE = True
except ImportError:
    CHARTS_AVAILABLE = False

import core as local_core
import update_manager
from deployment_config import DeploymentConfig, load_config, mode_label, save_config
from lan_server import LanServerController

DEPLOYMENT_CONFIG = load_config()
if DEPLOYMENT_CONFIG.is_workstation:
    import remote_core as core
else:
    core = local_core

APP_TITLE = f"{core.APP_NAME} {core.VERSION} — {mode_label(DEPLOYMENT_CONFIG.mode)}"

APP_STYLE = """
QMainWindow, QWidget { background: #f5f7fb; color: #172033; font-family: 'Segoe UI'; font-size: 10pt; }
QToolBar { background: #12355b; border: none; spacing: 6px; padding: 7px; }
QToolBar QLabel { color: white; font-size: 15pt; font-weight: 700; padding: 0 12px; }
QPushButton { background: #1665d8; color: white; border: none; border-radius: 6px; padding: 7px 13px; font-weight: 600; }
QPushButton:hover { background: #0f56bd; }
QPushButton:disabled { background: #a9b7c8; }
QPushButton#secondary { background: #e7edf5; color: #23334d; }
QPushButton#danger { background: #c73d3d; }
QLineEdit, QComboBox, QSpinBox, QPlainTextEdit, QTextEdit { background: white; border: 1px solid #cfd8e5; border-radius: 5px; padding: 5px; }
QTableView { background: white; alternate-background-color: #f8fafc; border: 1px solid #d8e0ea; gridline-color: #e8edf3; selection-background-color: #dbeafe; selection-color: #172033; }
QHeaderView::section { background: #e9eff7; color: #24344f; padding: 7px; border: none; border-right: 1px solid #d4dce7; font-weight: 700; }
QTabWidget::pane { border: 1px solid #d8e0ea; background: white; }
QTabBar::tab { background: #e9eff7; padding: 9px 15px; margin-right: 2px; }
QTabBar::tab:selected { background: #1665d8; color: white; }
QGroupBox { background: white; border: 1px solid #d8e0ea; border-radius: 8px; margin-top: 10px; font-weight: 700; }
QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 6px; }
QFrame#kpiCard { background: white; border: 1px solid #dce4ee; border-radius: 10px; }
QLabel#kpiValue { color: #12355b; font-size: 22pt; font-weight: 800; }
QLabel#kpiTitle { color: #607086; font-size: 9pt; }
QLabel#sectionTitle { font-size: 14pt; font-weight: 800; color: #12355b; }
"""


def display_value(value: Any) -> str:
    if value is None:
        return ""
    text = str(value)
    if len(text) >= 10 and text[4:5] == "-" and text[7:8] == "-":
        try:
            date_part = text[:10]
            y, m, d = date_part.split("-")
            suffix = text[10:]
            return f"{d}/{m}/{y}{suffix}"
        except Exception:
            return text
    return text


class DictTableModel(QAbstractTableModel):
    def __init__(self, rows: list[dict[str, Any]] | None = None, columns: list[tuple[str, str]] | None = None):
        super().__init__()
        self.rows = rows or []
        self.columns = columns or []

    def set_data(self, rows: list[dict[str, Any]], columns: list[tuple[str, str]] | None = None) -> None:
        self.beginResetModel()
        self.rows = rows
        if columns is not None:
            self.columns = columns
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()) -> int:  # noqa: N802
        return len(self.rows)

    def columnCount(self, parent=QModelIndex()) -> int:  # noqa: N802
        return len(self.columns)

    def data(self, index: QModelIndex, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        key = self.columns[index.column()][0]
        value = self.rows[index.row()].get(key, "")
        if role == Qt.ItemDataRole.DisplayRole:
            return display_value(value)
        if role == Qt.ItemDataRole.TextAlignmentRole and isinstance(value, (int, float)):
            return int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        if role == Qt.ItemDataRole.BackgroundRole:
            severity = self.rows[index.row()].get("severity")
            if severity == "error":
                return QColor("#fee2e2")
            if severity == "warning":
                return QColor("#fff7d6")
        return None

    def headerData(self, section: int, orientation: Qt.Orientation, role=Qt.ItemDataRole.DisplayRole):  # noqa: N802
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        if orientation == Qt.Orientation.Horizontal:
            return self.columns[section][1]
        return str(section + 1)

    def record_at(self, row: int) -> dict[str, Any] | None:
        if 0 <= row < len(self.rows):
            return self.rows[row]
        return None


class KpiCard(QFrame):
    def __init__(self, title: str):
        super().__init__()
        self.setObjectName("kpiCard")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        self.value_label = QLabel("0")
        self.value_label.setObjectName("kpiValue")
        self.title_label = QLabel(title)
        self.title_label.setObjectName("kpiTitle")
        layout.addWidget(self.value_label)
        layout.addWidget(self.title_label)

    def set_value(self, value: Any) -> None:
        self.value_label.setText(f"{value:,}" if isinstance(value, int) else str(value))


class DashboardTab(QWidget):
    def __init__(self):
        super().__init__()
        root = QVBoxLayout(self)
        title_row = QHBoxLayout()
        title = QLabel("Tổng quan giám sát dịch bệnh")
        title.setObjectName("sectionTitle")
        refresh = QPushButton("Làm mới")
        refresh.clicked.connect(self.refresh)
        title_row.addWidget(title)
        title_row.addStretch()
        title_row.addWidget(refresh)
        root.addLayout(title_row)

        kpi_grid = QGridLayout()
        self.cards = {
            "case_records": KpiCard("Bản ghi ca bệnh"),
            "outbreak_records": KpiCard("Ổ dịch"),
            "active_outbreaks": KpiCard("Ổ dịch đang hoạt động"),
            "reported_cases": KpiCard("Tổng ca mắc trong ổ dịch"),
            "deaths": KpiCard("Tử vong"),
            "quality_issues": KpiCard("Cảnh báo chất lượng"),
        }
        for i, card in enumerate(self.cards.values()):
            kpi_grid.addWidget(card, i // 3, i % 3)
        root.addLayout(kpi_grid)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.addWidget(QLabel("Thống kê theo bệnh"))
        self.disease_table = QTableView()
        self.disease_table.setAlternatingRowColors(True)
        self.disease_model = DictTableModel(columns=[
            ("disease", "Bệnh"),
            ("outbreak_count", "Số ổ dịch"),
            ("case_count", "Số ca"),
            ("active_count", "Đang hoạt động"),
            ("death_count", "Tử vong"),
        ])
        self.disease_table.setModel(self.disease_model)
        self.disease_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        left_layout.addWidget(self.disease_table)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.addWidget(QLabel("Ổ dịch đang hoạt động"))
        self.active_table = QTableView()
        self.active_table.setAlternatingRowColors(True)
        self.active_model = DictTableModel(columns=[
            ("disease", "Bệnh"),
            ("location", "Địa điểm"),
            ("first_onset_date", "Khởi phát đầu"),
            ("case_count", "Ca mắc"),
        ])
        self.active_table.setModel(self.active_model)
        self.active_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        right_layout.addWidget(self.active_table)
        splitter.addWidget(left)
        splitter.addWidget(right)
        splitter.setSizes([650, 650])
        root.addWidget(splitter, 1)

        self.chart_container = QWidget()
        self.chart_layout = QHBoxLayout(self.chart_container)
        self.chart_layout.setContentsMargins(0, 0, 0, 0)
        root.addWidget(self.chart_container, 1)
        self.refresh()

    def _clear_charts(self):
        while self.chart_layout.count():
            item = self.chart_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

    def refresh(self):
        stats = core.dashboard_stats()
        for key, card in self.cards.items():
            card.set_value(stats.get(key, 0))
        diseases = core.disease_summary()
        active = core.recent_active_outbreaks()
        self.disease_model.set_data(diseases)
        self.active_model.set_data(active)
        self._clear_charts()
        if not CHARTS_AVAILABLE:
            note = QLabel("Cài PyQt6-Charts để hiển thị biểu đồ trực quan.")
            note.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.chart_layout.addWidget(note)
            return
        self.chart_layout.addWidget(self._disease_chart(diseases))
        self.chart_layout.addWidget(self._monthly_chart(core.monthly_outbreak_summary()))

    def _disease_chart(self, rows: list[dict[str, Any]]) -> QChartView:
        top = rows[:8]
        series = QBarSeries()
        bar_set = QBarSet("Ổ dịch")
        categories = []
        for row in top:
            bar_set.append(float(row["outbreak_count"]))
            name = str(row["disease"] or "Không rõ")
            categories.append(name.replace("Bệnh ", "")[:22])
        series.append(bar_set)
        chart = QChart()
        chart.addSeries(series)
        chart.setTitle("Số ổ dịch theo bệnh")
        chart.setAnimationOptions(QChart.AnimationOption.SeriesAnimations)
        axis_x = QBarCategoryAxis()
        axis_x.append(categories)
        axis_y = QValueAxis()
        axis_y.setLabelFormat("%.0f")
        axis_y.setMin(0)
        chart.addAxis(axis_x, Qt.AlignmentFlag.AlignBottom)
        chart.addAxis(axis_y, Qt.AlignmentFlag.AlignLeft)
        series.attachAxis(axis_x)
        series.attachAxis(axis_y)
        chart.legend().setVisible(False)
        return QChartView(chart)

    def _monthly_chart(self, rows: list[dict[str, Any]]) -> QChartView:
        series = QBarSeries()
        outbreak_set = QBarSet("Ổ dịch")
        case_set = QBarSet("Ca mắc")
        categories = []
        for row in rows:
            outbreak_set.append(float(row["outbreak_count"]))
            case_set.append(float(row["case_count"]))
            month = str(row["month"])
            categories.append(month[5:7] + "/" + month[:4])
        series.append(outbreak_set)
        series.append(case_set)
        chart = QChart()
        chart.addSeries(series)
        chart.setTitle("Diễn biến ổ dịch theo tháng")
        axis_x = QBarCategoryAxis()
        axis_x.append(categories)
        axis_y = QValueAxis()
        axis_y.setLabelFormat("%.0f")
        axis_y.setMin(0)
        chart.addAxis(axis_x, Qt.AlignmentFlag.AlignBottom)
        chart.addAxis(axis_y, Qt.AlignmentFlag.AlignLeft)
        series.attachAxis(axis_x)
        series.attachAxis(axis_y)
        chart.legend().setVisible(True)
        return QChartView(chart)


class RecordDetailsDialog(QDialog):
    def __init__(self, title: str, record: dict[str, Any], labels: dict[str, str], parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(760, 650)
        layout = QVBoxLayout(self)
        table = QTableView()
        rows = [{"field": labels.get(k, k), "value": display_value(v)} for k, v in record.items() if k not in {"raw_json", "row_hash"}]
        table.setModel(DictTableModel(rows, [("field", "Trường"), ("value", "Giá trị")]))
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        table.verticalHeader().setVisible(False)
        layout.addWidget(table)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)


class OutbreakDialog(QDialog):
    def __init__(self, record: dict[str, Any] | None = None, parent=None):
        super().__init__(parent)
        self.record = record or {}
        self.setWindowTitle("Cập nhật ổ dịch" if record else "Thêm ổ dịch")
        self.resize(680, 620)
        root = QVBoxLayout(self)
        form = QFormLayout()
        self.fields: dict[str, QLineEdit | QComboBox | QSpinBox] = {}
        for label, key in core.OUTBREAK_FIELDS:
            if key == "source_stt":
                continue
            if key in {"case_count", "death_count", "sample_count", "positive_count"}:
                widget = QSpinBox()
                widget.setMaximum(10_000_000)
                widget.setValue(int(self.record.get(key) or 0))
            elif key == "status":
                widget = QComboBox()
                widget.addItems(["", "Đang hoạt động", "Đã kết thúc"])
                current = str(self.record.get(key) or "")
                if current and widget.findText(current) < 0:
                    widget.addItem(current)
                widget.setCurrentText(current)
            else:
                widget = QLineEdit(str(self.record.get(key) or ""))
                if key in core.DATE_FIELDS:
                    widget.setPlaceholderText("dd/mm/yyyy")
                if key in core.DATETIME_FIELDS:
                    widget.setPlaceholderText("dd/mm/yyyy HH:MM")
            self.fields[key] = widget
            form.addRow(label + ":", widget)
        root.addLayout(form)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def values(self) -> dict[str, Any]:
        data: dict[str, Any] = {}
        for key, widget in self.fields.items():
            if isinstance(widget, QSpinBox):
                data[key] = widget.value()
            elif isinstance(widget, QComboBox):
                data[key] = widget.currentText()
            else:
                data[key] = widget.text().strip()
        return data

    def accept(self):
        data = self.values()
        if not data.get("disease") or not data.get("location"):
            QMessageBox.warning(self, "Thiếu thông tin", "Tên bệnh và địa điểm ổ dịch là bắt buộc.")
            return
        super().accept()


class RecordsTab(QWidget):
    def __init__(self, entity_type: str):
        super().__init__()
        self.entity_type = entity_type
        self.page = 1
        self.page_size = 200
        self.total = 0
        root = QVBoxLayout(self)

        filter_box = QGroupBox("Bộ lọc")
        filters = QHBoxLayout(filter_box)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Tìm họ tên, mã số, địa chỉ, đơn vị báo cáo...")
        self.search.returnPressed.connect(self.refresh)
        self.disease = QComboBox()
        self.status = QComboBox()
        self.area = QComboBox()
        self.disease.addItem("Tất cả bệnh", "")
        self.status.addItem("Tất cả trạng thái", "")
        self.area.addItem("Tất cả địa bàn", "")
        self.refresh_filters()
        for widget in (self.disease, self.status, self.area):
            widget.currentIndexChanged.connect(self._filter_changed)
        btn_search = QPushButton("Tra cứu")
        btn_search.clicked.connect(self.refresh)
        btn_export = QPushButton("Xuất Excel/CSV")
        btn_export.setObjectName("secondary")
        btn_export.clicked.connect(self.export_data)
        filters.addWidget(self.search, 3)
        filters.addWidget(self.disease, 2)
        filters.addWidget(self.status, 1)
        filters.addWidget(self.area, 2)
        filters.addWidget(btn_search)
        filters.addWidget(btn_export)
        root.addWidget(filter_box)

        action_row = QHBoxLayout()
        self.title = QLabel("Danh sách ca bệnh" if entity_type == "case" else "Danh sách ổ dịch")
        self.title.setObjectName("sectionTitle")
        action_row.addWidget(self.title)
        action_row.addStretch()
        if entity_type == "outbreak":
            btn_add = QPushButton("Thêm ổ dịch")
            btn_add.clicked.connect(self.add_outbreak)
            btn_edit = QPushButton("Sửa")
            btn_edit.setObjectName("secondary")
            btn_edit.clicked.connect(self.edit_selected)
            btn_delete = QPushButton("Xóa")
            btn_delete.setObjectName("danger")
            btn_delete.clicked.connect(self.delete_selected)
            action_row.addWidget(btn_add)
            action_row.addWidget(btn_edit)
            action_row.addWidget(btn_delete)
        root.addLayout(action_row)

        self.table = QTableView()
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableView.SelectionMode.SingleSelection)
        self.table.doubleClicked.connect(self.show_details)
        if entity_type == "case":
            columns = [
                ("case_code", "Mã số"), ("full_name", "Họ tên"), ("birth_date_raw", "Ngày sinh"),
                ("gender", "Giới"), ("commune", "Xã/Phường"), ("main_diagnosis", "Chẩn đoán"),
                ("onset_date", "Khởi phát"), ("current_status", "Tình trạng"),
                ("report_datetime", "Báo cáo"), ("reporting_unit", "Đơn vị báo cáo"),
            ]
        else:
            columns = [
                ("disease", "Tên bệnh"), ("location", "Địa điểm"), ("admin_area", "Địa bàn"),
                ("first_onset_date", "Khởi phát đầu"), ("last_onset_date", "Khởi phát cuối"),
                ("status", "Trạng thái"), ("case_count", "Ca mắc"), ("death_count", "Tử vong"),
                ("sample_count", "Mẫu XN"), ("positive_count", "Mẫu (+)"),
                ("report_datetime", "Ngày báo cáo"), ("reporting_unit", "Đơn vị báo cáo"),
            ]
        self.model = DictTableModel(columns=columns)
        self.table.setModel(self.model)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        if entity_type == "case":
            header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
            header.setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)
        else:
            header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
            header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        root.addWidget(self.table, 1)

        pager = QHBoxLayout()
        self.prev_btn = QPushButton("← Trang trước")
        self.prev_btn.setObjectName("secondary")
        self.prev_btn.clicked.connect(self.prev_page)
        self.next_btn = QPushButton("Trang sau →")
        self.next_btn.setObjectName("secondary")
        self.next_btn.clicked.connect(self.next_page)
        self.page_label = QLabel()
        pager.addWidget(self.prev_btn)
        pager.addWidget(self.page_label)
        pager.addWidget(self.next_btn)
        pager.addStretch()
        root.addLayout(pager)
        self.refresh()

    def _filter_changed(self):
        self.page = 1
        self.refresh()

    def refresh_filters(self):
        try:
            if self.entity_type == "case":
                disease_values = core.list_filter_values("case", "main_diagnosis")
                status_values = sorted(set(core.list_filter_values("case", "record_status") + core.list_filter_values("case", "current_status")))
                area_values = core.list_filter_values("case", "commune")
            else:
                disease_values = core.list_filter_values("outbreak", "disease")
                status_values = core.list_filter_values("outbreak", "status")
                area_values = core.list_filter_values("outbreak", "admin_area")
            for combo, values in ((self.disease, disease_values), (self.status, status_values), (self.area, area_values)):
                current = combo.currentData()
                combo.blockSignals(True)
                while combo.count() > 1:
                    combo.removeItem(1)
                for value in values:
                    combo.addItem(value, value)
                idx = combo.findData(current)
                combo.setCurrentIndex(idx if idx >= 0 else 0)
                combo.blockSignals(False)
        except Exception:
            pass

    def refresh(self):
        rows, total = core.query_records(
            self.entity_type,
            search=self.search.text().strip(),
            disease=self.disease.currentData() or "",
            status=self.status.currentData() or "",
            admin_area=self.area.currentData() or "",
            page=self.page,
            page_size=self.page_size,
        )
        self.total = total
        self.model.set_data(rows)
        pages = max(1, math.ceil(total / self.page_size))
        if self.page > pages:
            self.page = pages
            return self.refresh()
        self.page_label.setText(f"Trang {self.page}/{pages} — {total:,} bản ghi")
        self.prev_btn.setEnabled(self.page > 1)
        self.next_btn.setEnabled(self.page < pages)

    def selected_record(self) -> dict[str, Any] | None:
        indexes = self.table.selectionModel().selectedRows()
        if not indexes:
            QMessageBox.information(self, "Chưa chọn", "Hãy chọn một bản ghi trong danh sách.")
            return None
        return self.model.record_at(indexes[0].row())

    def show_details(self):
        record = self.selected_record()
        if not record:
            return
        full = core.get_record(self.entity_type, int(record["id"]))
        labels = core.CASE_LABELS if self.entity_type == "case" else core.OUTBREAK_LABELS
        labels = {**labels, "admin_area": "Địa bàn chuẩn hóa", "source_file": "File nguồn", "source_row": "Dòng nguồn", "imported_at": "Thời điểm nhập"}
        RecordDetailsDialog("Chi tiết bản ghi", full or record, labels, self).exec()

    def prev_page(self):
        if self.page > 1:
            self.page -= 1
            self.refresh()

    def next_page(self):
        if self.page * self.page_size < self.total:
            self.page += 1
            self.refresh()

    def export_data(self):
        path, _ = QFileDialog.getSaveFileName(self, "Xuất dữ liệu", "", "Excel (*.xlsx);;CSV (*.csv)")
        if not path:
            return
        if not Path(path).suffix:
            path += ".xlsx"
        try:
            count = core.export_filtered_records(
                path,
                self.entity_type,
                search=self.search.text().strip(),
                disease=self.disease.currentData() or "",
                status=self.status.currentData() or "",
                admin_area=self.area.currentData() or "",
            )
            QMessageBox.information(self, "Đã xuất", f"Đã xuất {count:,} bản ghi:\n{path}")
        except Exception as exc:
            QMessageBox.critical(self, "Không thể xuất", str(exc))

    def add_outbreak(self):
        dialog = OutbreakDialog(parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            try:
                core.save_outbreak(dialog.values())
                self.refresh_filters()
                self.refresh()
            except Exception as exc:
                QMessageBox.critical(self, "Không thể lưu", str(exc))

    def edit_selected(self):
        record = self.selected_record()
        if not record:
            return
        full = core.get_record("outbreak", int(record["id"]))
        dialog = OutbreakDialog(full, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            try:
                core.save_outbreak(dialog.values(), int(record["id"]))
                self.refresh_filters()
                self.refresh()
            except Exception as exc:
                QMessageBox.critical(self, "Không thể lưu", str(exc))

    def delete_selected(self):
        record = self.selected_record()
        if not record:
            return
        answer = QMessageBox.question(self, "Xác nhận xóa", "Xóa ổ dịch đã chọn? CSDL sẽ được sao lưu trước khi xóa.")
        if answer == QMessageBox.StandardButton.Yes:
            try:
                core.delete_record("outbreak", int(record["id"]))
                self.refresh()
            except Exception as exc:
                QMessageBox.critical(self, "Không thể xóa", str(exc))


class ImportTab(QWidget):
    def __init__(self, after_import=None):
        super().__init__()
        self.after_import = after_import
        root = QVBoxLayout(self)
        title = QLabel("Nhập dữ liệu từ Excel")
        title.setObjectName("sectionTitle")
        root.addWidget(title)
        note = QLabel(
            "Ứng dụng tự nhận diện file ca bệnh hoặc ổ dịch qua tiêu đề cột. "
            "Dòng giống hệt đã nhập trước đó sẽ được bỏ qua bằng mã băm."
        )
        note.setWordWrap(True)
        root.addWidget(note)
        row = QHBoxLayout()
        self.path = QLineEdit()
        self.path.setReadOnly(True)
        browse = QPushButton("Chọn file...")
        browse.clicked.connect(self.browse)
        self.import_btn = QPushButton("Nhập vào CSDL")
        self.import_btn.clicked.connect(self.do_import)
        row.addWidget(self.path, 1)
        row.addWidget(browse)
        row.addWidget(self.import_btn)
        root.addLayout(row)
        self.files: list[str] = []
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        root.addWidget(self.log, 1)
        history_box = QGroupBox("Lịch sử nhập gần đây")
        history_layout = QVBoxLayout(history_box)
        self.history = QTableView()
        self.history_model = DictTableModel(columns=[
            ("imported_at", "Thời điểm"), ("file_name", "File"), ("entity_type", "Loại"),
            ("rows_read", "Đã đọc"), ("inserted", "Đã thêm"), ("duplicates", "Trùng"),
            ("issue_count", "Cảnh báo"),
        ])
        self.history.setModel(self.history_model)
        self.history.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        history_layout.addWidget(self.history)
        root.addWidget(history_box, 1)
        self.refresh_history()

    def browse(self):
        files, _ = QFileDialog.getOpenFileNames(self, "Chọn file Excel", "", "Excel (*.xlsx *.xlsm)")
        if files:
            self.files = files
            self.path.setText("; ".join(files))

    def do_import(self):
        if not self.files:
            QMessageBox.information(self, "Chưa chọn file", "Hãy chọn ít nhất một file Excel.")
            return
        self.import_btn.setEnabled(False)
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            for file in self.files:
                try:
                    summary = core.import_excel(file)
                    self.log.appendPlainText("✓ " + summary.as_text())
                except Exception as exc:
                    self.log.appendPlainText(f"✗ {Path(file).name}: {exc}")
            self.refresh_history()
            if self.after_import:
                self.after_import()
        finally:
            QApplication.restoreOverrideCursor()
            self.import_btn.setEnabled(True)

    def refresh_history(self):
        rows = core.list_import_batches()
        for row in rows:
            row["entity_type"] = "Ca bệnh" if row["entity_type"] == "case" else "Ổ dịch"
        self.history_model.set_data(rows)



class DuplicateReviewDialog(QDialog):
    def __init__(self, group: dict[str, Any], parent=None):
        super().__init__(parent)
        self.group = group
        self.setWindowTitle(f"Duyệt nhóm trùng #{group['group_id']}")
        self.resize(1050, 600)
        root = QVBoxLayout(self)
        note = QLabel(
            f"<b>{group['confidence']} — điểm {group['score']}/100</b><br>"
            f"Lý do: {group['reasons']}<br><br>"
            "Chọn một bản ghi để giữ. Các bản ghi còn lại chỉ bị xóa sau khi xác nhận; "
            "CSDL được sao lưu trước thao tác."
        )
        note.setWordWrap(True)
        root.addWidget(note)
        self.keep_combo = QComboBox()
        for record in group["records"]:
            if group["entity_type"] == "case":
                caption = f"ID {record['id']} — {record.get('full_name') or ''} — {record.get('case_code') or 'không mã'}"
            else:
                caption = f"ID {record['id']} — {record.get('disease') or ''} — {record.get('location') or ''}"
            source = f"{record.get('source_file') or ''}:{record.get('source_row') or ''}"
            self.keep_combo.addItem(f"{caption} — nguồn {source}", int(record["id"]))
        form = QFormLayout()
        form.addRow("Bản ghi giữ lại:", self.keep_combo)
        root.addLayout(form)
        self.table = QTableView()
        self.table.setAlternatingRowColors(True)
        if group["entity_type"] == "case":
            columns = [
                ("id", "ID"), ("case_code", "Mã ca"), ("full_name", "Họ tên"),
                ("birth_date_raw", "Ngày sinh"), ("gender", "Giới"), ("phone", "Điện thoại"),
                ("commune", "Xã/phường"), ("main_diagnosis", "Chẩn đoán"),
                ("onset_date", "Khởi phát"), ("source_file", "File nguồn"), ("source_row", "Dòng"),
            ]
        else:
            columns = [
                ("id", "ID"), ("disease", "Bệnh"), ("location", "Địa điểm"),
                ("admin_area", "Địa bàn"), ("first_onset_date", "Khởi phát đầu"),
                ("status", "Trạng thái"), ("case_count", "Ca mắc"),
                ("reporting_unit", "Đơn vị báo cáo"), ("source_file", "File nguồn"), ("source_row", "Dòng"),
            ]
        self.table.setModel(DictTableModel(group["records"], columns))
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        root.addWidget(self.table, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("Giữ bản đã chọn và xóa bản còn lại")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    @property
    def keep_id(self) -> int:
        return int(self.keep_combo.currentData())


class DuplicateTab(QWidget):
    def __init__(self, after_change=None):
        super().__init__()
        self.after_change = after_change
        self.groups: list[dict[str, Any]] = []
        root = QVBoxLayout(self)
        title_row = QHBoxLayout()
        title = QLabel("Lọc trùng dữ liệu")
        title.setObjectName("sectionTitle")
        self.entity = QComboBox()
        self.entity.addItem("Ca bệnh", "case")
        self.entity.addItem("Ổ dịch", "outbreak")
        self.min_score = QSpinBox()
        self.min_score.setRange(50, 100)
        self.min_score.setValue(65)
        self.min_score.setSuffix(" điểm")
        scan = QPushButton("Quét dữ liệu")
        scan.clicked.connect(self.refresh)
        review = QPushButton("Duyệt nhóm đã chọn")
        review.clicked.connect(self.review_selected)
        export = QPushButton("Xuất kết quả")
        export.setObjectName("secondary")
        export.clicked.connect(self.export)
        title_row.addWidget(title)
        title_row.addStretch()
        title_row.addWidget(QLabel("Đối tượng:"))
        title_row.addWidget(self.entity)
        title_row.addWidget(QLabel("Ngưỡng:"))
        title_row.addWidget(self.min_score)
        title_row.addWidget(scan)
        title_row.addWidget(review)
        title_row.addWidget(export)
        root.addLayout(title_row)
        info = QLabel(
            "Trùng tuyệt đối khi khớp mã ca hoặc CCCD/CMND. Các trường hợp còn lại được chấm điểm "
            "theo họ tên, năm sinh, điện thoại, địa bàn, chẩn đoán và ngày khởi phát. "
            "Ứng dụng không tự động xóa hay gộp."
        )
        info.setWordWrap(True)
        root.addWidget(info)
        self.summary = QLabel("Chưa quét dữ liệu.")
        root.addWidget(self.summary)
        self.table = QTableView()
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableView.SelectionMode.SingleSelection)
        self.table.doubleClicked.connect(self.review_selected)
        self.model = DictTableModel(columns=[
            ("group_id", "Nhóm"), ("confidence", "Mức"), ("score", "Điểm"),
            ("record_count", "Số bản ghi"), ("summary", "Tóm tắt"), ("reasons", "Lý do"),
        ])
        self.table.setModel(self.model)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)
        root.addWidget(self.table, 1)

    def clear_results(self):
        self.groups = []
        self.model.set_data([])
        self.summary.setText("Dữ liệu đã thay đổi. Bấm Quét dữ liệu để cập nhật kết quả lọc trùng.")

    def refresh(self):
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            self.groups = core.find_duplicate_groups(
                self.entity.currentData(), min_score=self.min_score.value()
            )
            rows = []
            for group in self.groups:
                row = {k: v for k, v in group.items() if k != "records"}
                row["severity"] = "error" if group["score"] >= 85 else "warning"
                rows.append(row)
            self.model.set_data(rows)
            total_records = sum(int(group["record_count"]) for group in self.groups)
            self.summary.setText(
                f"Phát hiện {len(self.groups):,} nhóm với {total_records:,} bản ghi cần duyệt."
                if self.groups else "Không phát hiện bản ghi trùng theo ngưỡng hiện tại."
            )
        except Exception as exc:
            QMessageBox.critical(self, "Không thể lọc trùng", str(exc))
        finally:
            QApplication.restoreOverrideCursor()

    def selected_group(self) -> dict[str, Any] | None:
        indexes = self.table.selectionModel().selectedRows()
        if not indexes:
            QMessageBox.information(self, "Chưa chọn", "Hãy chọn một nhóm trùng trong danh sách.")
            return None
        row = indexes[0].row()
        return self.groups[row] if 0 <= row < len(self.groups) else None

    def review_selected(self):
        group = self.selected_group()
        if not group:
            return
        dialog = DuplicateReviewDialog(group, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        keep_id = dialog.keep_id
        remove_ids = [int(record_id) for record_id in group["record_ids"] if int(record_id) != keep_id]
        answer = QMessageBox.question(
            self,
            "Xác nhận xử lý trùng",
            f"Giữ bản ghi ID {keep_id} và xóa {len(remove_ids)} bản ghi còn lại?\n"
            "CSDL sẽ được sao lưu trước khi xóa.",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            result = core.remove_duplicate_records(group["entity_type"], keep_id, remove_ids)
            QMessageBox.information(
                self,
                "Đã xử lý",
                f"Đã giữ ID {result['kept_id']} và xóa {result['removed_count']} bản ghi.\n"
                f"Bản sao lưu: {result['backup_file']}",
            )
            if self.after_change:
                self.after_change()
            self.refresh()
        except Exception as exc:
            QMessageBox.critical(self, "Không thể xử lý trùng", str(exc))

    def export(self):
        if not self.groups:
            QMessageBox.information(self, "Không có dữ liệu", "Hãy quét dữ liệu trước khi xuất.")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Xuất kết quả lọc trùng", "ket_qua_loc_trung.xlsx", "Excel (*.xlsx);;CSV (*.csv)"
        )
        if not path:
            return
        columns = ["Nhóm", "Mức", "Điểm", "Số bản ghi", "Danh sách ID", "Tóm tắt", "Lý do"]
        rows = [[
            g["group_id"], g["confidence"], g["score"], g["record_count"],
            ", ".join(map(str, g["record_ids"])), g["summary"], g["reasons"],
        ] for g in self.groups]
        core.export_rows(path, columns, rows)
        QMessageBox.information(self, "Đã xuất", path)


class WorkstationConnectionDialog(QDialog):
    def __init__(self, config: DeploymentConfig, parent=None):
        super().__init__(parent)
        self.config = config
        self.setWindowTitle("Kết nối máy chủ LAN")
        self.resize(560, 220)
        root = QVBoxLayout(self)
        form = QFormLayout()
        self.url = QLineEdit(config.server_url)
        self.url.setPlaceholderText("http://192.168.1.10:8765")
        self.password = QLineEdit(config.password)
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.password.setPlaceholderText("Để trống nếu máy chủ không đặt mật khẩu")
        form.addRow("Địa chỉ máy chủ:", self.url)
        form.addRow("Mật khẩu:", self.password)
        root.addLayout(form)
        self.status = QLabel("Nhập IP/cổng của máy chủ trong cùng mạng LAN.")
        self.status.setWordWrap(True)
        root.addWidget(self.status)
        row = QHBoxLayout()
        test = QPushButton("Kiểm tra kết nối")
        test.clicked.connect(self.test_connection)
        row.addWidget(test)
        row.addStretch()
        root.addLayout(row)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def _save_values(self):
        url = self.url.text().strip().rstrip("/")
        if not (url.startswith("http://") or url.startswith("https://")):
            raise ValueError("Địa chỉ máy chủ phải bắt đầu bằng http:// hoặc https://")
        self.config.server_url = url
        self.config.password = self.password.text()
        save_config(self.config)

    def test_connection(self):
        try:
            self._save_values()
            import remote_core
            info = remote_core.health()
            self.status.setText(f"Kết nối thành công: {info.get('app')} {info.get('version')} — cổng {info.get('port')}")
        except Exception as exc:
            self.status.setText(f"Kết nối thất bại: {exc}")

    def accept(self):
        try:
            self._save_values()
        except Exception as exc:
            QMessageBox.warning(self, "Cấu hình chưa hợp lệ", str(exc))
            return
        super().accept()


class ServerTab(QWidget):
    def __init__(self, controller: LanServerController, config: DeploymentConfig):
        super().__init__()
        self.controller = controller
        self.config = config
        root = QVBoxLayout(self)
        title = QLabel("Máy chủ chia sẻ dữ liệu trong mạng LAN")
        title.setObjectName("sectionTitle")
        root.addWidget(title)
        note = QLabel(
            "Máy chủ sử dụng CSDL SQLite tại máy này và chia sẻ dữ liệu qua API HTTP trong mạng LAN. "
            "Máy trạm không mở trực tiếp file .db. Khi Windows hỏi quyền tường lửa, chỉ cho phép mạng Riêng tư."
        )
        note.setWordWrap(True)
        root.addWidget(note)
        box = QGroupBox("Cấu hình server")
        form = QFormLayout(box)
        self.port = QSpinBox()
        self.port.setRange(1, 65535)
        self.port.setValue(config.server_port)
        self.password = QLineEdit(config.password)
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.password.setPlaceholderText("Để trống = không yêu cầu mật khẩu")
        self.auto_start = QCheckBox("Tự khởi động server khi mở ứng dụng")
        self.auto_start.setChecked(config.auto_start_server)
        form.addRow("Cổng LAN:", self.port)
        form.addRow("Mật khẩu máy trạm:", self.password)
        form.addRow("", self.auto_start)
        root.addWidget(box)
        self.status = QLabel()
        self.status.setWordWrap(True)
        root.addWidget(self.status)
        row = QHBoxLayout()
        save = QPushButton("Lưu cấu hình")
        save.clicked.connect(self.save_settings)
        self.start_button = QPushButton("Khởi động server")
        self.start_button.clicked.connect(self.start_server)
        self.stop_button = QPushButton("Dừng server")
        self.stop_button.setObjectName("danger")
        self.stop_button.clicked.connect(self.stop_server)
        row.addWidget(save)
        row.addWidget(self.start_button)
        row.addWidget(self.stop_button)
        row.addStretch()
        root.addLayout(row)
        detail = QTextEdit()
        detail.setReadOnly(True)
        detail.setMaximumHeight(170)
        detail.setHtml(
            f"<b>CSDL máy chủ:</b> {local_core.DB_PATH}<br>"
            f"<b>Thư mục dữ liệu:</b> {local_core.DATA_DIR}<br><br>"
            "Máy chủ tự tạo CSDL khi chưa có. Mật khẩu để trống nghĩa là mọi máy trong LAN biết địa chỉ đều có thể kết nối."
        )
        root.addWidget(detail)
        root.addStretch()
        self.refresh()

    def save_settings(self):
        was_running = self.controller.running
        if was_running:
            self.controller.stop()
        self.config.server_port = self.port.value()
        self.config.password = self.password.text()
        self.config.auto_start_server = self.auto_start.isChecked()
        save_config(self.config)
        self.controller.config = self.config
        if was_running:
            self.start_server()
        else:
            self.refresh()

    def start_server(self):
        try:
            self.save_settings_without_restart()
            address = self.controller.start()
            self.status.setText(f"Server đang hoạt động tại <b>{address}</b>. Máy trạm dùng địa chỉ này để kết nối.")
        except Exception as exc:
            self.status.setText(f"Không khởi động được server: {exc}")
        self.refresh_buttons()

    def save_settings_without_restart(self):
        self.config.server_port = self.port.value()
        self.config.password = self.password.text()
        self.config.auto_start_server = self.auto_start.isChecked()
        save_config(self.config)
        self.controller.config = self.config

    def stop_server(self):
        self.controller.stop()
        self.refresh()

    def auto_start_server(self):
        if self.config.auto_start_server and not self.controller.running:
            self.start_server()

    def refresh_buttons(self):
        self.start_button.setEnabled(not self.controller.running)
        self.stop_button.setEnabled(self.controller.running)

    def refresh(self):
        if self.controller.running:
            auth = "có mật khẩu" if self.config.password else "không mật khẩu"
            self.status.setText(f"Server đang hoạt động tại <b>{self.controller.address}</b> — {auth}.")
        else:
            self.status.setText("Server đang dừng.")
        self.refresh_buttons()


class QualityTab(QWidget):
    def __init__(self):
        super().__init__()
        root = QVBoxLayout(self)
        row = QHBoxLayout()
        title = QLabel("Chất lượng dữ liệu")
        title.setObjectName("sectionTitle")
        self.entity = QComboBox()
        self.entity.addItem("Tất cả loại", "")
        self.entity.addItem("Ca bệnh", "case")
        self.entity.addItem("Ổ dịch", "outbreak")
        self.severity = QComboBox()
        self.severity.addItem("Tất cả mức", "")
        self.severity.addItem("Lỗi", "error")
        self.severity.addItem("Cảnh báo", "warning")
        self.severity.addItem("Thông tin", "info")
        refresh = QPushButton("Làm mới")
        refresh.clicked.connect(self.refresh)
        export = QPushButton("Xuất danh sách")
        export.setObjectName("secondary")
        export.clicked.connect(self.export)
        row.addWidget(title)
        row.addStretch()
        row.addWidget(self.entity)
        row.addWidget(self.severity)
        row.addWidget(refresh)
        row.addWidget(export)
        root.addLayout(row)
        self.table = QTableView()
        self.table.setAlternatingRowColors(True)
        self.model = DictTableModel(columns=[
            ("severity", "Mức"), ("entity_type", "Đối tượng"), ("entity_id", "ID"),
            ("issue_type", "Loại lỗi"), ("description", "Mô tả"),
            ("source_file", "File nguồn"), ("source_row", "Dòng"),
        ])
        self.table.setModel(self.model)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        root.addWidget(self.table)
        self.entity.currentIndexChanged.connect(self.refresh)
        self.severity.currentIndexChanged.connect(self.refresh)
        self.refresh()

    def refresh(self):
        rows = core.list_quality_issues(severity=self.severity.currentData() or "", entity_type=self.entity.currentData() or "")
        for row in rows:
            row["entity_type"] = "Ca bệnh" if row["entity_type"] == "case" else "Ổ dịch"
            row["severity"] = {"error": "Lỗi", "warning": "Cảnh báo", "info": "Thông tin"}.get(row["severity"], row["severity"])
        self.model.set_data(rows)

    def export(self):
        if not self.model.rows:
            QMessageBox.information(self, "Không có dữ liệu", "Danh sách cảnh báo đang trống.")
            return
        path, _ = QFileDialog.getSaveFileName(self, "Xuất cảnh báo", "bao_cao_chat_luong.xlsx", "Excel (*.xlsx);;CSV (*.csv)")
        if not path:
            return
        columns = [label for _, label in self.model.columns]
        rows = [[r.get(key, "") for key, _ in self.model.columns] for r in self.model.rows]
        core.export_rows(path, columns, rows)
        QMessageBox.information(self, "Đã xuất", path)


class SqlTab(QWidget):
    QUICK_SQL = {
        "Tổng quan ổ dịch": """SELECT disease AS ten_benh, COUNT(*) AS so_o_dich, SUM(case_count) AS so_ca, SUM(death_count) AS tu_vong\nFROM outbreaks\nGROUP BY disease\nORDER BY so_o_dich DESC;""",
        "Ổ dịch đang hoạt động": """SELECT disease, location, first_onset_date, case_count, reporting_unit\nFROM outbreaks\nWHERE status = 'Đang hoạt động'\nORDER BY first_onset_date DESC;""",
        "Báo cáo ổ dịch muộn trên 2 ngày": """SELECT disease, location, first_onset_date, report_datetime,\n       CAST(julianday(substr(report_datetime,1,10)) - julianday(first_onset_date) AS INTEGER) AS so_ngay\nFROM outbreaks\nWHERE first_onset_date <> '' AND report_datetime <> ''\n  AND julianday(substr(report_datetime,1,10)) - julianday(first_onset_date) > 2\nORDER BY so_ngay DESC;""",
        "Ca bệnh theo chẩn đoán": """SELECT main_diagnosis, COUNT(*) AS so_ca\nFROM cases\nGROUP BY main_diagnosis\nORDER BY so_ca DESC;""",
    }

    def __init__(self):
        super().__init__()
        root = QVBoxLayout(self)
        row = QHBoxLayout()
        title = QLabel("Truy vấn SQL chỉ đọc")
        title.setObjectName("sectionTitle")
        self.quick = QComboBox()
        self.quick.addItem("Chọn câu lệnh nhanh...")
        self.quick.addItems(self.QUICK_SQL.keys())
        self.quick.currentTextChanged.connect(self.load_quick)
        run = QPushButton("Chạy truy vấn")
        run.clicked.connect(self.run_query)
        export = QPushButton("Xuất kết quả")
        export.setObjectName("secondary")
        export.clicked.connect(self.export)
        row.addWidget(title)
        row.addStretch()
        row.addWidget(self.quick)
        row.addWidget(run)
        row.addWidget(export)
        root.addLayout(row)
        self.editor = QPlainTextEdit("SELECT * FROM outbreaks ORDER BY first_onset_date DESC LIMIT 200;")
        self.editor.setMaximumHeight(150)
        self.editor.setFont(QFont("Consolas", 10))
        root.addWidget(self.editor)
        self.table = QTableView()
        self.model = DictTableModel()
        self.table.setModel(self.model)
        self.table.setAlternatingRowColors(True)
        root.addWidget(self.table)

    def load_quick(self, text: str):
        if text in self.QUICK_SQL:
            self.editor.setPlainText(self.QUICK_SQL[text])

    def run_query(self):
        try:
            columns, values = core.execute_select(self.editor.toPlainText())
            rows = [dict(zip(columns, row)) for row in values]
            self.model.set_data(rows, [(c, c) for c in columns])
            self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
            QMessageBox.information(self, "Kết quả", f"Trả về {len(rows):,} dòng (tối đa 5.000).")
        except Exception as exc:
            QMessageBox.critical(self, "Lỗi truy vấn", str(exc))

    def export(self):
        if not self.model.rows:
            QMessageBox.information(self, "Chưa có kết quả", "Hãy chạy truy vấn trước.")
            return
        path, _ = QFileDialog.getSaveFileName(self, "Xuất kết quả", "ket_qua_truy_van.xlsx", "Excel (*.xlsx);;CSV (*.csv)")
        if not path:
            return
        columns = [label for _, label in self.model.columns]
        rows = [[r.get(key, "") for key, _ in self.model.columns] for r in self.model.rows]
        core.export_rows(path, columns, rows)
        QMessageBox.information(self, "Đã xuất", path)


class SettingsTab(QWidget):
    def __init__(self, config: DeploymentConfig):
        super().__init__()
        self.config = config
        root = QVBoxLayout(self)
        title = QLabel("Dữ liệu, sao lưu và cập nhật")
        title.setObjectName("sectionTitle")
        root.addWidget(title)
        info = QTextEdit()
        info.setReadOnly(True)
        info.setMaximumHeight(210)
        deployment_detail = (
            f"Máy chủ: {config.server_url}" if config.is_workstation
            else f"CSDL: {local_core.DB_PATH}"
        )
        info.setHtml(
            f"<b>Phiên bản:</b> {core.VERSION}<br>"
            f"<b>Chế độ:</b> {mode_label(config.mode)}<br>"
            f"<b>{deployment_detail}</b><br>"
            f"<b>Thư mục cấu hình cục bộ:</b> {local_core.USER_DATA_DIR}<br><br>"
            "CSDL nghiệp vụ không nằm trong bộ cài. Cài đè hoặc cập nhật không ghi đè thư mục dữ liệu người dùng."
        )
        root.addWidget(info)

        update_box = QGroupBox("Cập nhật trực tiếp từ Google Drive")
        update_layout = QVBoxLayout(update_box)
        self.update_status = QLabel(
            "Bấm kiểm tra để đọc phiên bản mới từ update_manifest.json trên Google Drive."
        )
        self.update_status.setWordWrap(True)
        update_layout.addWidget(self.update_status)
        update_row = QHBoxLayout()
        self.update_button = QPushButton("Kiểm tra cập nhật")
        self.update_button.clicked.connect(lambda: self.check_update(silent=False))
        update_row.addWidget(self.update_button)
        update_row.addStretch()
        update_layout.addLayout(update_row)
        root.addWidget(update_box)

        buttons = QHBoxLayout()
        backup = QPushButton("Sao lưu CSDL ngay")
        backup.clicked.connect(self.backup)
        open_data = QPushButton("Mở thư mục dữ liệu" if not config.is_workstation else "Mở thư mục cấu hình")
        open_data.setObjectName("secondary")
        open_data.clicked.connect(lambda: local_core.open_folder(local_core.DATA_DIR if not config.is_workstation else local_core.USER_DATA_DIR))
        open_backup = QPushButton("Mở thư mục sao lưu")
        open_backup.setObjectName("secondary")
        open_backup.clicked.connect(lambda: local_core.open_folder(local_core.BACKUP_DIR))
        open_backup.setVisible(not config.is_workstation)
        buttons.addWidget(backup)
        buttons.addWidget(open_data)
        buttons.addWidget(open_backup)
        buttons.addStretch()
        root.addLayout(buttons)
        root.addStretch()

    def backup(self):
        try:
            path = core.create_backup()
            QMessageBox.information(self, "Đã sao lưu", str(path))
        except Exception as exc:
            QMessageBox.critical(self, "Không thể sao lưu", str(exc))

    def check_update(self, silent: bool = False):
        self.update_button.setEnabled(False)
        self.update_status.setText("Đang kiểm tra phiên bản trên Google Drive...")
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            info = update_manager.fetch_manifest()
        except Exception as exc:
            self.update_status.setText(f"Không kiểm tra được cập nhật: {exc}")
            if not silent:
                QMessageBox.warning(self, "Không kiểm tra được cập nhật", str(exc))
            return
        finally:
            QApplication.restoreOverrideCursor()
            self.update_button.setEnabled(True)

        if not update_manager.is_newer_version(info.version, core.VERSION):
            self.update_status.setText(f"Đang dùng phiên bản mới nhất: {core.VERSION}.")
            if not silent:
                QMessageBox.information(self, "Không có bản mới", f"Phiên bản hiện tại: {core.VERSION}")
            return

        self.update_status.setText(f"Có phiên bản {info.version}: {info.notes or 'Không có ghi chú.'}")
        answer = QMessageBox.question(
            self,
            "Có bản cập nhật mới",
            f"Phiên bản hiện tại: {core.VERSION}\n"
            f"Phiên bản mới: {info.version}\n\n"
            f"{info.notes or 'Không có ghi chú phát hành.'}\n\n"
            "Ứng dụng sẽ sao lưu CSDL, tải gói cập nhật, tự đóng rồi mở lại. Tiếp tục?",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        try:
            backup_path = core.create_backup()
            cache_dir = core.UPDATE_CACHE_DIR
            zip_path = cache_dir / info.file_name
            progress = QProgressDialog("Đang tải bản cập nhật từ Google Drive...", "Hủy", 0, 100, self)
            progress.setWindowTitle("Cập nhật ứng dụng")
            progress.setWindowModality(Qt.WindowModality.WindowModal)
            progress.setMinimumDuration(0)

            def on_progress(downloaded: int, total: int | None):
                if progress.wasCanceled():
                    raise update_manager.UpdateError("Đã hủy tải bản cập nhật.")
                if total:
                    progress.setMaximum(100)
                    progress.setValue(min(99, int(downloaded * 100 / total)))
                else:
                    progress.setMaximum(0)
                QApplication.processEvents()

            update_manager.download_drive_file(info.release_file_id, zip_path, on_progress, timeout=180)
            progress.setLabelText("Đang kiểm tra tính toàn vẹn của gói cập nhật...")
            progress.setMaximum(0)
            QApplication.processEvents()
            update_manager.verify_download(zip_path, info.sha256)
            progress.close()
            self.update_status.setText(
                f"Đã tải phiên bản {info.version}. CSDL đã sao lưu tại {backup_path.name}."
            )
            update_manager.launch_update_and_exit(zip_path, core.BASE_DIR, info.package_root)
            QApplication.quit()
        except Exception as exc:
            try:
                progress.close()
            except Exception:
                pass
            self.update_status.setText(f"Cập nhật chưa hoàn tất: {exc}")
            QMessageBox.critical(self, "Không thể cập nhật", str(exc))


class MainWindow(QMainWindow):
    def __init__(self, config: DeploymentConfig):
        super().__init__()
        self.config = config
        self.server_controller = LanServerController(config) if config.is_server else None
        self.setWindowTitle(APP_TITLE)
        self.resize(1500, 900)
        toolbar = QToolBar()
        toolbar.setMovable(False)
        toolbar.addWidget(QLabel(f"CDC • GIÁM SÁT DỊCH BỆNH • {mode_label(config.mode).upper()}"))
        self.addToolBar(toolbar)
        self.tabs = QTabWidget()
        self.dashboard = DashboardTab()
        self.cases = RecordsTab("case")
        self.outbreaks = RecordsTab("outbreak")
        self.duplicates = DuplicateTab(self.refresh_after_duplicate)
        self.quality = QualityTab()
        self.import_tab = ImportTab(self.refresh_all)
        self.sql = SqlTab()
        self.settings = SettingsTab(config)
        self.server_tab = ServerTab(self.server_controller, config) if self.server_controller else None
        self.tabs.addTab(self.dashboard, "Tổng quan")
        self.tabs.addTab(self.cases, "Ca bệnh")
        self.tabs.addTab(self.outbreaks, "Ổ dịch")
        self.tabs.addTab(self.duplicates, "Lọc trùng")
        self.tabs.addTab(self.import_tab, "Nhập Excel")
        self.tabs.addTab(self.quality, "Chất lượng dữ liệu")
        self.tabs.addTab(self.sql, "Truy vấn SQL")
        if self.server_tab:
            self.tabs.addTab(self.server_tab, "Server")
        self.tabs.addTab(self.settings, "Sao lưu & cập nhật")
        self.tabs.currentChanged.connect(self.on_tab_changed)
        self.setCentralWidget(self.tabs)
        self._build_menu()
        self.statusBar().showMessage(f"Chế độ: {mode_label(config.mode)} — Dữ liệu: {core.DB_PATH}")
        QTimer.singleShot(1800, lambda: self.settings.check_update(silent=True))
        if self.server_tab:
            QTimer.singleShot(500, self.server_tab.auto_start_server)

    def _build_menu(self):
        file_menu = self.menuBar().addMenu("&Tệp")
        import_action = QAction("Nhập dữ liệu Excel...", self)
        import_action.triggered.connect(lambda: self.tabs.setCurrentWidget(self.import_tab))
        file_menu.addAction(import_action)
        open_data = QAction("Mở thư mục dữ liệu", self)
        open_data.triggered.connect(lambda: local_core.open_folder(local_core.DATA_DIR))
        file_menu.addAction(open_data)
        file_menu.addSeparator()
        exit_action = QAction("Thoát", self)
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        tools_menu = self.menuBar().addMenu("&Công cụ")
        duplicate_action = QAction("Lọc trùng dữ liệu", self)
        duplicate_action.triggered.connect(lambda: self.tabs.setCurrentWidget(self.duplicates))
        tools_menu.addAction(duplicate_action)
        backup_action = QAction("Sao lưu CSDL", self)
        backup_action.triggered.connect(self.settings.backup)
        tools_menu.addAction(backup_action)
        update_action = QAction("Kiểm tra cập nhật", self)
        update_action.triggered.connect(lambda: self.settings.check_update(silent=False))
        tools_menu.addAction(update_action)
        if self.config.is_workstation:
            connection_action = QAction("Cấu hình kết nối máy chủ...", self)
            connection_action.triggered.connect(self.configure_workstation)
            tools_menu.addAction(connection_action)
        if self.server_tab:
            server_action = QAction("Mở quản lý Server", self)
            server_action.triggered.connect(lambda: self.tabs.setCurrentWidget(self.server_tab))
            tools_menu.addAction(server_action)

        view_menu = self.menuBar().addMenu("&Đi tới")
        for index in range(self.tabs.count()):
            action = QAction(self.tabs.tabText(index), self)
            action.triggered.connect(lambda checked=False, i=index: self.tabs.setCurrentIndex(i))
            view_menu.addAction(action)

        help_menu = self.menuBar().addMenu("&Trợ giúp")
        about_action = QAction("Thông tin ứng dụng", self)
        about_action.triggered.connect(self.show_about)
        help_menu.addAction(about_action)

    def configure_workstation(self):
        dialog = WorkstationConnectionDialog(self.config, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            QMessageBox.information(self, "Đã lưu", "Cấu hình đã lưu. Ứng dụng sẽ tải lại dữ liệu từ máy chủ.")
            self.refresh_all()

    def show_about(self):
        QMessageBox.information(
            self,
            "Thông tin ứng dụng",
            f"{core.APP_NAME} {core.VERSION}\n"
            f"Chế độ: {mode_label(self.config.mode)}\n"
            "Quản lý ca bệnh, ổ dịch, lọc trùng và chia sẻ dữ liệu trong mạng LAN."
        )

    def refresh_after_duplicate(self):
        self.dashboard.refresh()
        self.cases.refresh()
        self.outbreaks.refresh()
        self.quality.refresh()

    def refresh_all(self):
        self.dashboard.refresh()
        self.cases.refresh_filters()
        self.cases.refresh()
        self.outbreaks.refresh_filters()
        self.outbreaks.refresh()
        self.quality.refresh()
        self.duplicates.clear_results()
        if self.server_tab:
            self.server_tab.refresh()

    def on_tab_changed(self, index: int):
        widget = self.tabs.widget(index)
        if hasattr(widget, "refresh"):
            try:
                widget.refresh()
            except Exception as exc:
                self.statusBar().showMessage(f"Không làm mới được dữ liệu: {exc}")

    def closeEvent(self, event):  # noqa: N802
        if self.server_controller:
            self.server_controller.stop()
        super().closeEvent(event)


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName(local_core.APP_NAME)
    app.setStyleSheet(APP_STYLE)
    config = load_config()
    if config.is_workstation:
        import remote_core
        try:
            remote_core.health()
        except Exception as exc:
            answer = QMessageBox.question(
                None,
                "Chưa kết nối được máy chủ",
                f"{exc}\n\nMở cấu hình kết nối máy chủ?",
            )
            if answer != QMessageBox.StandardButton.Yes:
                return 1
            dialog = WorkstationConnectionDialog(config)
            if dialog.exec() != QDialog.DialogCode.Accepted:
                return 1
            try:
                remote_core.health()
            except Exception as retry_exc:
                QMessageBox.critical(None, "Không kết nối được", str(retry_exc))
                return 1
    else:
        local_core.init_db()
    window = MainWindow(config)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
