from __future__ import annotations

import math
import os
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
    QInputDialog,
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
    QTableWidget,
    QTableWidgetItem,
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
import backup_manager
import update_manager
from deployment_config import DeploymentConfig, load_config, mode_label, save_config
from duplicate_config import (
    CASE_CRITERIA_DEFS,
    CaseDuplicateCriteria,
    DuplicateRules,
    load_case_criteria,
    load_rules,
    save_case_criteria,
    save_rules,
)
from lan_server import LanServerController, configure_windows_firewall, port_available

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



class DuplicateRulesDialog(QDialog):
    """Cấu hình trọng số lọc trùng ổ dịch. Ca bệnh dùng CaseDuplicateCriteriaDialog (chọn tiêu chí)."""

    OUTBREAK_LABELS = {
        "disease": "Tên bệnh", "location_exact": "Địa điểm trùng", "location_near": "Địa điểm gần giống",
        "area": "Địa bàn", "onset_exact": "Khởi phát trùng ngày", "onset_near": "Khởi phát gần nhau",
        "reporting_unit": "Đơn vị báo cáo",
    }

    def __init__(self, rules: DuplicateRules, parent=None):
        super().__init__(parent)
        self.rules = rules
        self.setWindowTitle("Cấu hình trọng số lọc trùng ổ dịch")
        self.resize(560, 480)
        root = QVBoxLayout(self)
        general = QGroupBox("Ngưỡng phân loại")
        form = QFormLayout(general)
        self.min_score = QSpinBox(); self.min_score.setRange(40, 100); self.min_score.setValue(rules.min_score)
        self.definite = QSpinBox(); self.definite.setRange(50, 100); self.definite.setValue(rules.definite_score)
        form.addRow("Điểm tối thiểu để đưa vào danh sách:", self.min_score)
        form.addRow("Điểm xác định trùng chắc chắn:", self.definite)
        root.addWidget(general)
        self.outbreak_inputs = self._weight_box(root, "Trọng số ổ dịch", rules.outbreak_weights, self.OUTBREAK_LABELS)
        note = QLabel("Tổng điểm cuối được giới hạn ở 100. Lọc trùng ca bệnh không còn dùng điểm số — xem nút \"Tiêu chí...\".")
        note.setWordWrap(True); root.addWidget(note)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept); buttons.rejected.connect(self.reject); root.addWidget(buttons)

    def _weight_box(self, root, title, values, labels):
        box = QGroupBox(title); form = QFormLayout(box); inputs = {}
        for key, label in labels.items():
            spin = QSpinBox(); spin.setRange(0, 100); spin.setValue(int(values.get(key, 0))); spin.setSuffix(" điểm")
            form.addRow(label + ":", spin); inputs[key] = spin
        root.addWidget(box); return inputs

    def accept(self):
        if self.definite.value() < self.min_score.value():
            QMessageBox.warning(self, "Ngưỡng chưa hợp lệ", "Điểm trùng chắc chắn phải lớn hơn hoặc bằng điểm tối thiểu.")
            return
        self.rules.min_score = self.min_score.value(); self.rules.definite_score = self.definite.value()
        self.rules.outbreak_weights = {k: w.value() for k, w in self.outbreak_inputs.items()}
        save_rules(self.rules)
        super().accept()


class CaseDuplicateCriteriaDialog(QDialog):
    """Chọn tiêu chí lọc trùng ca bệnh — thay cho chấm điểm/trọng số."""

    def __init__(self, criteria: CaseDuplicateCriteria, parent=None):
        super().__init__(parent)
        self.criteria = criteria
        self.setWindowTitle("Tiêu chí lọc trùng ca bệnh")
        self.resize(480, 420)
        root = QVBoxLayout(self)
        info = QLabel(
            "Hai ca bệnh được coi là trùng nếu khớp ít nhất một tiêu chí đang chọn. "
            "Không còn tính điểm — mỗi tiêu chí là một quy tắc so khớp rõ ràng.\n"
            "Lưu ý: \"Họ tên gần giống\" và \"Ngày khởi phát gần nhau\" chỉ so sánh các ca "
            "trong cùng một xã/phường."
        )
        info.setWordWrap(True); root.addWidget(info)
        box = QGroupBox("Tiêu chí"); form = QVBoxLayout(box)
        self.checks: dict[str, QCheckBox] = {}
        for criterion_id, label in CASE_CRITERIA_DEFS:
            check = QCheckBox(label); check.setChecked(criterion_id in criteria.enabled)
            form.addWidget(check); self.checks[criterion_id] = check
        root.addWidget(box)
        params = QGroupBox("Tham số"); params_form = QFormLayout(params)
        self.name_threshold = QSpinBox(); self.name_threshold.setRange(50, 100); self.name_threshold.setSuffix(" %")
        self.name_threshold.setValue(criteria.name_similarity_percent)
        self.onset_days = QSpinBox(); self.onset_days.setRange(0, 60); self.onset_days.setSuffix(" ngày")
        self.onset_days.setValue(criteria.onset_max_days)
        params_form.addRow("Ngưỡng họ tên gần giống:", self.name_threshold)
        params_form.addRow("Khởi phát lệch tối đa:", self.onset_days)
        root.addWidget(params)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept); buttons.rejected.connect(self.reject); root.addWidget(buttons)

    def accept(self):
        enabled = [criterion_id for criterion_id, check in self.checks.items() if check.isChecked()]
        if not enabled:
            QMessageBox.warning(self, "Chưa chọn tiêu chí", "Hãy chọn ít nhất một tiêu chí lọc trùng.")
            return
        self.criteria.enabled = enabled
        self.criteria.name_similarity_percent = self.name_threshold.value()
        self.criteria.onset_max_days = self.onset_days.value()
        save_case_criteria(self.criteria)
        super().accept()


class DuplicateReviewDialog(QDialog):
    CASE_MERGE_FIELDS = [
        "case_code", "full_name", "birth_date_raw", "gender", "national_id", "phone", "current_address",
        "commune", "main_diagnosis", "onset_date", "report_datetime", "reporting_unit", "current_status", "record_status",
    ]
    OUTBREAK_MERGE_FIELDS = [
        "disease", "location", "first_onset_date", "last_onset_date", "end_date", "status", "case_count",
        "death_count", "sample_count", "positive_count", "report_datetime", "reporting_unit",
    ]

    def __init__(self, group: dict[str, Any], parent=None):
        super().__init__(parent)
        self.group = group
        self.setWindowTitle(f"Duyệt và hợp nhất nhóm trùng #{group['group_id']}")
        self.resize(1180, 760)
        root = QVBoxLayout(self)
        if group["entity_type"] == "case":
            heading = f"<b>{group['confidence']} — tiêu chí khớp: {group['reasons']}</b>"
            case_codes = ", ".join(code for code in group.get("case_codes") or [] if code)
            if case_codes:
                heading += f"<br>Mã ca bệnh liên quan: {case_codes}"
        else:
            heading = f"<b>{group['confidence']} — điểm {group['score']}/100</b><br>Lý do: {group['reasons']}"
        note = QLabel(
            f"{heading}<br><br>"
            "Chọn bản ghi chính và giá trị cuối cho từng trường. Bản còn lại được đưa vào Thùng rác, không xóa vĩnh viễn; "
            "CSDL được sao lưu trước thao tác."
        )
        note.setWordWrap(True); root.addWidget(note)
        self.keep_combo = QComboBox()
        for record in group["records"]:
            caption = (f"ID {record['id']} — {record.get('full_name') or ''} — {record.get('case_code') or 'không mã'}"
                       if group["entity_type"] == "case" else
                       f"ID {record['id']} — {record.get('disease') or ''} — {record.get('location') or ''}")
            self.keep_combo.addItem(caption, int(record["id"]))
        form = QFormLayout(); form.addRow("Bản ghi chính:", self.keep_combo); root.addLayout(form)
        splitter = QSplitter(Qt.Orientation.Vertical)
        self.table = QTableView(); self.table.setAlternatingRowColors(True)
        columns = ([
            ("id", "ID"), ("case_code", "Mã ca"), ("full_name", "Họ tên"), ("birth_date_raw", "Ngày sinh"),
            ("gender", "Giới"), ("phone", "Điện thoại"), ("commune", "Xã/phường"),
            ("main_diagnosis", "Chẩn đoán"), ("onset_date", "Khởi phát"), ("source_file", "File nguồn"),
        ] if group["entity_type"] == "case" else [
            ("id", "ID"), ("disease", "Bệnh"), ("location", "Địa điểm"), ("admin_area", "Địa bàn"),
            ("first_onset_date", "Khởi phát đầu"), ("status", "Trạng thái"), ("case_count", "Ca mắc"),
            ("reporting_unit", "Đơn vị báo cáo"), ("source_file", "File nguồn"),
        ])
        self.table.setModel(DictTableModel(group["records"], columns))
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        splitter.addWidget(self.table)
        merge_box = QGroupBox("Chọn giá trị cho bản ghi sau hợp nhất")
        merge_layout = QVBoxLayout(merge_box)
        fields = self.CASE_MERGE_FIELDS if group["entity_type"] == "case" else self.OUTBREAK_MERGE_FIELDS
        labels = core.CASE_LABELS if group["entity_type"] == "case" else core.OUTBREAK_LABELS
        self.merge_table = QTableWidget(len(fields), 2)
        self.merge_table.setHorizontalHeaderLabels(["Trường dữ liệu", "Giá trị giữ lại"])
        self.merge_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.merge_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.merge_combos: dict[str, QComboBox] = {}
        keep_record = group["records"][0]
        for row, field in enumerate(fields):
            combo = QComboBox(); values = []
            for record in group["records"]:
                value = record.get(field)
                text = "" if value is None else str(value)
                if text not in values: values.append(text)
            label_text = labels.get(field, field)
            non_empty_values = {value for value in values if value}
            if len(non_empty_values) > 1: label_text = "⚠ " + label_text
            label_item = QTableWidgetItem(label_text); label_item.setFlags(label_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.merge_table.setItem(row, 0, label_item)
            for value in values: combo.addItem(value, value)
            default = "" if keep_record.get(field) is None else str(keep_record.get(field))
            index = combo.findData(default); combo.setCurrentIndex(index if index >= 0 else 0)
            self.merge_table.setCellWidget(row, 1, combo); self.merge_combos[field] = combo
        self.keep_combo.currentIndexChanged.connect(self.apply_keep_defaults)
        merge_layout.addWidget(self.merge_table); splitter.addWidget(merge_box); splitter.setSizes([300, 360])
        root.addWidget(splitter, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("Hợp nhất và đưa bản còn lại vào Thùng rác")
        buttons.accepted.connect(self.accept); buttons.rejected.connect(self.reject); root.addWidget(buttons)

    def apply_keep_defaults(self):
        keep_id = int(self.keep_combo.currentData())
        record = next((item for item in self.group["records"] if int(item["id"]) == keep_id), None)
        if not record: return
        for field, combo in self.merge_combos.items():
            value = "" if record.get(field) is None else str(record.get(field))
            index = combo.findData(value)
            if index >= 0: combo.setCurrentIndex(index)

    @property
    def keep_id(self) -> int: return int(self.keep_combo.currentData())

    @property
    def merged_values(self) -> dict[str, Any]:
        return {field: combo.currentData() for field, combo in self.merge_combos.items()}


class DuplicateHistoryDialog(QDialog):
    def __init__(self, after_restore=None, parent=None):
        super().__init__(parent); self.after_restore = after_restore
        self.setWindowTitle("Lịch sử hợp nhất và Thùng rác"); self.resize(950, 540)
        root = QVBoxLayout(self)
        info = QLabel("Mỗi thao tác đều có bản sao lưu. Khôi phục sẽ đưa các bản ghi trong Thùng rác trở lại CSDL.")
        info.setWordWrap(True); root.addWidget(info)
        self.model = DictTableModel(columns=[
            ("id", "Mã thao tác"), ("entity_label", "Đối tượng"), ("keep_id", "ID giữ lại"),
            ("action_label", "Xử lý"), ("trash_count", "Đã đưa vào rác"), ("pending_count", "Có thể khôi phục"),
            ("created_at", "Thời điểm"), ("restored_at", "Đã khôi phục"),
        ])
        self.table = QTableView(); self.table.setModel(self.model); self.table.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableView.SelectionMode.SingleSelection); self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        root.addWidget(self.table, 1)
        row = QHBoxLayout(); refresh = QPushButton("Làm mới"); refresh.clicked.connect(self.refresh)
        restore = QPushButton("Khôi phục nhóm đã chọn"); restore.clicked.connect(self.restore_selected)
        row.addWidget(refresh); row.addWidget(restore); row.addStretch(); root.addLayout(row)
        close = QDialogButtonBox(QDialogButtonBox.StandardButton.Close); close.rejected.connect(self.reject); root.addWidget(close)
        self.refresh()

    def refresh(self):
        rows = core.list_duplicate_actions()
        for item in rows:
            item["entity_label"] = "Ca bệnh" if item.get("entity_type") == "case" else "Ổ dịch"
            item["action_label"] = "Hợp nhất" if item.get("action_type") == "merge" else "Loại trùng"
        self.model.set_data(rows)

    def restore_selected(self):
        indexes = self.table.selectionModel().selectedRows()
        if not indexes:
            QMessageBox.information(self, "Chưa chọn", "Hãy chọn một thao tác cần khôi phục."); return
        item = self.model.record_at(indexes[0].row())
        if not item or int(item.get("pending_count") or 0) <= 0:
            QMessageBox.information(self, "Không thể khôi phục", "Nhóm này không còn bản ghi trong Thùng rác."); return
        if QMessageBox.question(self, "Xác nhận khôi phục", "Khôi phục các bản ghi đã loại? CSDL hiện tại sẽ được sao lưu trước.") != QMessageBox.StandardButton.Yes:
            return
        try:
            result = core.restore_duplicate_action(int(item["id"]))
            QMessageBox.information(self, "Đã khôi phục", f"Đã khôi phục {result['restored_count']} bản ghi.\nSao lưu an toàn: {result['backup_file']}")
            self.refresh()
            if self.after_restore: self.after_restore()
        except Exception as exc:
            QMessageBox.critical(self, "Không thể khôi phục", str(exc))


class DuplicateTab(QWidget):
    CASE_COLUMNS = [
        ("group_id", "Nhóm"), ("confidence", "Mức"), ("case_codes_text", "Mã ca bệnh liên quan"),
        ("record_count", "Số bản ghi"), ("summary", "Tóm tắt"), ("reasons", "Tiêu chí khớp"),
    ]
    OUTBREAK_COLUMNS = [
        ("group_id", "Nhóm"), ("confidence", "Mức"), ("score", "Điểm"),
        ("record_count", "Số bản ghi"), ("summary", "Tóm tắt"), ("reasons", "Lý do"),
    ]

    def __init__(self, after_change=None):
        super().__init__(); self.after_change = after_change; self.groups = []; self.rules = load_rules()
        self.case_criteria = load_case_criteria()
        root = QVBoxLayout(self); title_row = QHBoxLayout(); title = QLabel("Lọc trùng dữ liệu"); title.setObjectName("sectionTitle")
        self.entity = QComboBox(); self.entity.addItem("Ca bệnh", "case"); self.entity.addItem("Ổ dịch", "outbreak")
        self.entity.currentIndexChanged.connect(self._on_entity_changed)
        self.min_score = QSpinBox(); self.min_score.setRange(40, 100); self.min_score.setValue(self.rules.min_score); self.min_score.setSuffix(" điểm")
        self.min_score_label = QLabel("Ngưỡng:")
        scan = QPushButton("Quét dữ liệu"); scan.clicked.connect(self.refresh)
        review = QPushButton("Duyệt & hợp nhất"); review.clicked.connect(self.review_selected)
        self.rules_btn = QPushButton("Tiêu chí..."); self.rules_btn.setObjectName("secondary"); self.rules_btn.clicked.connect(self.configure_rules)
        history = QPushButton("Thùng rác / lịch sử"); history.setObjectName("secondary"); history.clicked.connect(self.open_history)
        export = QPushButton("Xuất kết quả"); export.setObjectName("secondary"); export.clicked.connect(self.export)
        self.export_by_commune_btn = QPushButton("Xuất theo xã..."); self.export_by_commune_btn.setObjectName("secondary")
        self.export_by_commune_btn.clicked.connect(self.export_by_commune)
        title_row.addWidget(title); title_row.addStretch(); title_row.addWidget(QLabel("Đối tượng:")); title_row.addWidget(self.entity)
        title_row.addWidget(self.min_score_label); title_row.addWidget(self.min_score)
        for widget in (scan, review, self.rules_btn, history, export, self.export_by_commune_btn): title_row.addWidget(widget)
        root.addLayout(title_row)
        self.info = QLabel(); self.info.setWordWrap(True); root.addWidget(self.info)
        self.summary = QLabel("Chưa quét dữ liệu."); root.addWidget(self.summary)
        self.table = QTableView(); self.table.setAlternatingRowColors(True); self.table.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableView.SelectionMode.SingleSelection); self.table.doubleClicked.connect(self.review_selected)
        self.model = DictTableModel(columns=self.CASE_COLUMNS)
        self.table.setModel(self.model); self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch); self.table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)
        root.addWidget(self.table, 1)
        self._on_entity_changed()

    def _on_entity_changed(self):
        is_case = self.entity.currentData() == "case"
        self.rules_btn.setText("Tiêu chí..." if is_case else "Trọng số...")
        self.min_score_label.setVisible(not is_case); self.min_score.setVisible(not is_case)
        self.export_by_commune_btn.setVisible(is_case)
        self.info.setText(
            "Hai ca bệnh trùng nếu khớp ít nhất một tiêu chí đang chọn (không tính điểm). "
            "Bấm \"Tiêu chí...\" để thay đổi." if is_case else
            "Phát hiện trùng theo trọng số có thể cấu hình. Khi xử lý, người dùng chọn giá trị tốt nhất từng "
            "trường; bản còn lại vào Thùng rác và có thể khôi phục."
        )
        self.clear_results()

    def configure_rules(self):
        if self.entity.currentData() == "case":
            dialog = CaseDuplicateCriteriaDialog(self.case_criteria, self)
            if dialog.exec() == QDialog.DialogCode.Accepted:
                self.case_criteria = load_case_criteria(); self.clear_results()
        else:
            dialog = DuplicateRulesDialog(self.rules, self)
            if dialog.exec() == QDialog.DialogCode.Accepted:
                self.rules = load_rules(); self.min_score.setValue(self.rules.min_score); self.clear_results()

    def open_history(self): DuplicateHistoryDialog(self.after_change, self).exec()

    def clear_results(self):
        self.groups = []
        columns = self.CASE_COLUMNS if self.entity.currentData() == "case" else self.OUTBREAK_COLUMNS
        self.model.set_data([], columns)
        self.summary.setText("Dữ liệu hoặc quy tắc đã thay đổi. Bấm Quét dữ liệu để cập nhật.")

    def refresh(self):
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            entity_type = self.entity.currentData()
            if entity_type == "case":
                self.groups = core.find_duplicate_groups("case", criteria={
                    "enabled": self.case_criteria.enabled,
                    "name_similarity_percent": self.case_criteria.name_similarity_percent,
                    "onset_max_days": self.case_criteria.onset_max_days,
                })
                rows = []
                for group in self.groups:
                    row = {k: v for k, v in group.items() if k != "records"}
                    row["case_codes_text"] = ", ".join(code for code in group.get("case_codes") or [] if code)
                    row["severity"] = "error" if group["confidence"] == "Trùng chắc chắn" else "warning"
                    rows.append(row)
                self.model.set_data(rows, self.CASE_COLUMNS)
            else:
                weights = self.rules.weights_for(entity_type)
                self.groups = core.find_duplicate_groups(entity_type, min_score=self.min_score.value(), rules={"weights": weights, "definite_score": self.rules.definite_score})
                rows = []
                for group in self.groups:
                    row = {k: v for k, v in group.items() if k != "records"}; row["severity"] = "error" if group["score"] >= self.rules.definite_score else "warning"; rows.append(row)
                self.model.set_data(rows, self.OUTBREAK_COLUMNS)
            total = sum(int(g["record_count"]) for g in self.groups)
            self.summary.setText(f"Phát hiện {len(self.groups):,} nhóm với {total:,} bản ghi cần duyệt." if self.groups else "Không phát hiện bản ghi trùng theo tiêu chí/ngưỡng hiện tại.")
        except Exception as exc: QMessageBox.critical(self, "Không thể lọc trùng", str(exc))
        finally: QApplication.restoreOverrideCursor()

    def selected_group(self):
        indexes = self.table.selectionModel().selectedRows()
        if not indexes: QMessageBox.information(self, "Chưa chọn", "Hãy chọn một nhóm trùng trong danh sách."); return None
        row = indexes[0].row(); return self.groups[row] if 0 <= row < len(self.groups) else None

    def review_selected(self):
        group = self.selected_group()
        if not group: return
        dialog = DuplicateReviewDialog(group, self)
        if dialog.exec() != QDialog.DialogCode.Accepted: return
        keep_id = dialog.keep_id; remove_ids = [int(i) for i in group["record_ids"] if int(i) != keep_id]
        if QMessageBox.question(self, "Xác nhận hợp nhất", f"Giữ ID {keep_id}, hợp nhất giá trị đã chọn và đưa {len(remove_ids)} bản ghi vào Thùng rác?") != QMessageBox.StandardButton.Yes: return
        try:
            result = core.merge_duplicate_records(group["entity_type"], keep_id, remove_ids, dialog.merged_values)
            QMessageBox.information(self, "Đã hợp nhất", f"Đã giữ ID {result['kept_id']} và đưa {result['removed_count']} bản ghi vào Thùng rác.\nBản sao lưu: {result['backup_file']}")
            if self.after_change: self.after_change()
            self.refresh()
        except Exception as exc: QMessageBox.critical(self, "Không thể hợp nhất", str(exc))

    def export(self):
        if not self.groups: QMessageBox.information(self, "Không có dữ liệu", "Hãy quét dữ liệu trước khi xuất."); return
        path, _ = QFileDialog.getSaveFileName(self, "Xuất kết quả lọc trùng", "ket_qua_loc_trung.xlsx", "Excel (*.xlsx);;CSV (*.csv)")
        if not path: return
        if self.entity.currentData() == "case":
            columns = ["Nhóm", "Mức", "Mã ca bệnh liên quan", "Số bản ghi", "Danh sách ID", "Tóm tắt", "Tiêu chí khớp"]
            rows = [[
                g["group_id"], g["confidence"], ", ".join(code for code in g.get("case_codes") or [] if code),
                g["record_count"], ", ".join(map(str, g["record_ids"])), g["summary"], g["reasons"],
            ] for g in self.groups]
        else:
            columns = ["Nhóm", "Mức", "Điểm", "Số bản ghi", "Danh sách ID", "Tóm tắt", "Lý do"]
            rows = [[g["group_id"], g["confidence"], g["score"], g["record_count"], ", ".join(map(str, g["record_ids"])), g["summary"], g["reasons"]] for g in self.groups]
        core.export_rows(path, columns, rows); QMessageBox.information(self, "Đã xuất", path)

    def export_by_commune(self):
        path, _ = QFileDialog.getSaveFileName(self, "Xuất ca bệnh chia theo xã", "ca_benh_theo_xa.xlsx", "Excel (*.xlsx)")
        if not path: return
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            result = core.export_cases_by_commune(path, criteria={
                "enabled": self.case_criteria.enabled,
                "name_similarity_percent": self.case_criteria.name_similarity_percent,
                "onset_max_days": self.case_criteria.onset_max_days,
            })
            QMessageBox.information(
                self, "Đã xuất theo xã",
                f"Đã xuất {result['case_count']} ca bệnh vào {result['commune_count']} sheet xã.\n"
                f"{result['duplicate_group_count']} nhóm trùng, trong đó {result['cross_commune_group_count']} nhóm "
                f"trùng khác xã (đã gộp theo xã của ca vào viện gần nhất).\nFile: {result['path']}"
            )
        except Exception as exc:
            QMessageBox.critical(self, "Không thể xuất", str(exc))
        finally:
            QApplication.restoreOverrideCursor()


class WorkstationConnectionDialog(QDialog):
    def __init__(self, config: DeploymentConfig, parent=None):
        super().__init__(parent); self.config = config
        self.setWindowTitle("Kết nối máy chủ LAN"); self.resize(620, 300)
        root = QVBoxLayout(self); form = QFormLayout()
        self.url = QLineEdit(config.server_url); self.url.setPlaceholderText("http://192.168.1.10:8765")
        self.password = QLineEdit(config.password); self.password.setEchoMode(QLineEdit.EchoMode.Password); self.password.setPlaceholderText("Để trống nếu máy chủ không đặt mật khẩu")
        self.auto_reconnect = QCheckBox("Tự kết nối lại khi mạng chập chờn"); self.auto_reconnect.setChecked(config.auto_reconnect)
        form.addRow("Địa chỉ máy chủ:", self.url); form.addRow("Mật khẩu:", self.password); form.addRow("", self.auto_reconnect); root.addLayout(form)
        self.status = QLabel("Có thể nhập IP hoặc dùng nút Tìm máy chủ tự động."); self.status.setWordWrap(True); root.addWidget(self.status)
        row = QHBoxLayout(); discover = QPushButton("Tìm máy chủ tự động"); discover.clicked.connect(self.discover)
        test = QPushButton("Kiểm tra kết nối"); test.clicked.connect(self.test_connection)
        row.addWidget(discover); row.addWidget(test); row.addStretch(); root.addLayout(row)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept); buttons.rejected.connect(self.reject); root.addWidget(buttons)

    def _save_values(self):
        url = self.url.text().strip().rstrip("/")
        if not (url.startswith("http://") or url.startswith("https://")): raise ValueError("Địa chỉ máy chủ phải bắt đầu bằng http:// hoặc https://")
        self.config.server_url = url; self.config.password = self.password.text(); self.config.auto_reconnect = self.auto_reconnect.isChecked(); save_config(self.config)

    def discover(self):
        self.status.setText("Đang dò máy chủ trong mạng LAN..."); QApplication.processEvents()
        try:
            import remote_core
            servers = remote_core.discover_servers(timeout=2.0)
            if not servers: self.status.setText("Không tìm thấy máy chủ. Kiểm tra cùng mạng LAN và Windows Firewall."); return
            captions = [f"{s.get('server_name') or s.get('source_ip')} — {s.get('url')} — {'có mật khẩu' if s.get('password_required') else 'không mật khẩu'}" for s in servers]
            chosen = 0
            if len(servers) > 1:
                text, ok = QInputDialog.getItem(self, "Chọn máy chủ", "Máy chủ tìm thấy:", captions, 0, False)
                if not ok: return
                chosen = captions.index(text)
            server = servers[chosen]; self.url.setText(str(server["url"])); self.status.setText(f"Đã chọn {captions[chosen]}")
        except Exception as exc: self.status.setText(f"Không thể dò máy chủ: {exc}")

    def test_connection(self):
        try:
            self._save_values(); import remote_core; info = remote_core.health()
            self.status.setText(f"Kết nối thành công: {info.get('server_name') or info.get('app')} {info.get('version')} — cổng {info.get('port')}")
        except Exception as exc: self.status.setText(f"Kết nối thất bại: {exc}")

    def accept(self):
        try: self._save_values()
        except Exception as exc: QMessageBox.warning(self, "Cấu hình chưa hợp lệ", str(exc)); return
        super().accept()


class ServerTab(QWidget):
    def __init__(self, controller: LanServerController, config: DeploymentConfig):
        super().__init__(); self.controller = controller; self.config = config
        root = QVBoxLayout(self); title = QLabel("Máy chủ chia sẻ dữ liệu trong mạng LAN"); title.setObjectName("sectionTitle"); root.addWidget(title)
        note = QLabel("Máy trạm truy cập qua API, không mở trực tiếp file .db. Server tự dò trong LAN, theo dõi máy trạm và tạm khóa ghi trong lúc sao lưu.")
        note.setWordWrap(True); root.addWidget(note)
        box = QGroupBox("Cấu hình server"); form = QFormLayout(box)
        self.server_name = QLineEdit(config.server_name); self.server_name.setPlaceholderText("Tên hiển thị khi máy trạm tự dò")
        self.port = QSpinBox(); self.port.setRange(1, 65535); self.port.setValue(config.server_port)
        self.password = QLineEdit(config.password); self.password.setEchoMode(QLineEdit.EchoMode.Password); self.password.setPlaceholderText("Để trống = không yêu cầu mật khẩu")
        self.auto_start = QCheckBox("Tự khởi động server khi mở ứng dụng"); self.auto_start.setChecked(config.auto_start_server)
        self.discovery = QCheckBox("Cho phép máy trạm tự tìm server trong LAN"); self.discovery.setChecked(config.discovery_enabled)
        form.addRow("Tên máy chủ:", self.server_name); form.addRow("Cổng LAN:", self.port); form.addRow("Mật khẩu máy trạm:", self.password); form.addRow("", self.auto_start); form.addRow("", self.discovery)
        root.addWidget(box)
        secondary_box = QGroupBox("Máy chủ phụ (Google Apps Script) — dự phòng khi offline")
        secondary_form = QFormLayout(secondary_box)
        self.secondary_url = QLineEdit(config.secondary_webapp_url)
        self.secondary_url.setPlaceholderText("https://script.google.com/macros/s/XXXX/exec")
        self.secondary_key = QLineEdit(config.secondary_shared_key); self.secondary_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.secondary_key.setPlaceholderText("Khóa bí mật đặt trong Script Properties (SHARED_KEY)")
        secondary_form.addRow("URL Web App:", self.secondary_url)
        secondary_form.addRow("Khóa chia sẻ:", self.secondary_key)
        secondary_note = QLabel("Xem hướng dẫn triển khai trong google_apps_script/README.md.")
        secondary_note.setWordWrap(True); secondary_form.addRow("", secondary_note)
        root.addWidget(secondary_box)
        web_note = QLabel(
            "Trang web: /xa (Trạm Y tế xã nộp danh sách hằng tuần) và /cdc/hang-doi "
            "(CDC xem hàng đợi chia theo xã, nhập vào CSDL và đồng bộ máy chủ phụ)."
        )
        web_note.setWordWrap(True); root.addWidget(web_note)
        self.status = QLabel(); self.status.setWordWrap(True); root.addWidget(self.status)
        row = QHBoxLayout(); save = QPushButton("Lưu cấu hình"); save.clicked.connect(self.save_settings)
        self.start_button = QPushButton("Khởi động server"); self.start_button.clicked.connect(self.start_server)
        self.stop_button = QPushButton("Dừng server"); self.stop_button.setObjectName("danger"); self.stop_button.clicked.connect(self.stop_server)
        firewall = QPushButton("Cấu hình Windows Firewall"); firewall.setObjectName("secondary"); firewall.clicked.connect(self.configure_firewall)
        for widget in (save, self.start_button, self.stop_button, firewall): row.addWidget(widget)
        row.addStretch(); root.addLayout(row)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        client_box = QGroupBox("Máy trạm đã kết nối"); cl = QVBoxLayout(client_box)
        self.client_model = DictTableModel(columns=[("ip", "IP"), ("last_seen", "Truy cập cuối"), ("requests", "Số yêu cầu"), ("last_path", "Endpoint cuối")])
        self.client_table = QTableView(); self.client_table.setModel(self.client_model); self.client_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents); cl.addWidget(self.client_table)
        log_box = QGroupBox("Nhật ký truy cập gần đây"); ll = QVBoxLayout(log_box)
        self.log_model = DictTableModel(columns=[("time", "Thời điểm"), ("ip", "IP"), ("method", "Phương thức"), ("path", "Đường dẫn"), ("status", "Kết quả")])
        self.log_table = QTableView(); self.log_table.setModel(self.log_model); self.log_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents); ll.addWidget(self.log_table)
        splitter.addWidget(client_box); splitter.addWidget(log_box); splitter.setSizes([520, 650]); root.addWidget(splitter, 1)
        detail = QLabel(f"CSDL máy chủ: {local_core.DB_PATH}\nThư mục dữ liệu: {local_core.DATA_DIR}"); detail.setWordWrap(True); root.addWidget(detail)
        self.timer = QTimer(self); self.timer.timeout.connect(self.refresh); self.timer.start(3000); self.refresh()

    def _apply_fields(self):
        self.config.server_name = self.server_name.text().strip(); self.config.server_port = self.port.value(); self.config.password = self.password.text()
        self.config.auto_start_server = self.auto_start.isChecked(); self.config.discovery_enabled = self.discovery.isChecked()
        self.config.secondary_webapp_url = self.secondary_url.text().strip(); self.config.secondary_shared_key = self.secondary_key.text()
        save_config(self.config); self.controller.config = self.config

    def save_settings(self):
        was_running = self.controller.running
        if was_running: self.controller.stop()
        self._apply_fields()
        if was_running: self.start_server()
        else: self.refresh()

    def start_server(self):
        try:
            self._apply_fields()
            if not port_available(self.config.server_host, self.config.server_port): raise OSError(f"Cổng {self.config.server_port} đang được sử dụng.")
            address = self.controller.start(); self.status.setText(f"Server đang hoạt động tại <b>{address}</b>.")
        except Exception as exc: self.status.setText(f"Không khởi động được server: {exc}")
        self.refresh_buttons()

    def stop_server(self): self.controller.stop(); self.refresh()
    def auto_start_server(self):
        if self.config.auto_start_server and not self.controller.running: self.start_server()
    def refresh_buttons(self): self.start_button.setEnabled(not self.controller.running); self.stop_button.setEnabled(self.controller.running)

    def configure_firewall(self):
        answer = QMessageBox.question(self, "Windows Firewall", "Tạo quy tắc cho TCP server và UDP tự dò trên mạng Riêng tư? Có thể cần mở ứng dụng bằng quyền quản trị.")
        if answer != QMessageBox.StandardButton.Yes: return
        result = configure_windows_firewall(self.port.value())
        (QMessageBox.information if result.get("ok") else QMessageBox.warning)(self, "Windows Firewall", str(result.get("message")))

    def refresh(self):
        status = self.controller.status()
        if status["running"]:
            auth = "có mật khẩu" if status["password_required"] else "không mật khẩu"
            readonly = " — ĐANG SAO LƯU, CHỈ ĐỌC" if status.get("backup_in_progress") else ""
            discover = "tự dò LAN bật" if status.get("discovery_running") else "tự dò LAN tắt"
            self.status.setText(f"Server tại <b>{status['address']}</b> — {auth} — {discover} — {status['client_count']} máy trạm{readonly}.")
        else: self.status.setText("Server đang dừng." + (f" Lỗi gần nhất: {status.get('last_error')}" if status.get('last_error') else ""))
        self.client_model.set_data(status.get("clients", []))
        logs = []
        for item in status.get("logs", []): item = dict(item); item["status"] = "Thành công" if item.get("ok") else "Lỗi"; logs.append(item)
        self.log_model.set_data(logs); self.refresh_buttons()


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
    def __init__(self, config: DeploymentConfig, after_restore=None, server_controller=None):
        super().__init__(); self.config = config; self.after_restore = after_restore; self.server_controller = server_controller; self.policy = backup_manager.load_policy()
        root = QVBoxLayout(self); title = QLabel("Dữ liệu, sao lưu, phục hồi và cập nhật"); title.setObjectName("sectionTitle"); root.addWidget(title)
        info = QTextEdit(); info.setReadOnly(True); info.setMaximumHeight(145)
        deployment_detail = f"Máy chủ: {config.server_url}" if config.is_workstation else f"CSDL: {local_core.DB_PATH}"
        info.setHtml(f"<b>Phiên bản:</b> {core.VERSION}<br><b>Chế độ:</b> {mode_label(config.mode)}<br><b>{deployment_detail}</b><br><b>Thư mục cấu hình:</b> {local_core.USER_DATA_DIR}<br>CSDL nghiệp vụ không nằm trong bộ cài.")
        root.addWidget(info)
        if not config.is_workstation:
            policy_box = QGroupBox("Sao lưu tự động và lưu giữ"); form = QFormLayout(policy_box)
            self.backup_enabled = QCheckBox("Bật sao lưu tự động"); self.backup_enabled.setChecked(self.policy.enabled)
            self.interval = QSpinBox(); self.interval.setRange(1, 720); self.interval.setValue(self.policy.interval_hours); self.interval.setSuffix(" giờ")
            self.keep_daily = QSpinBox(); self.keep_daily.setRange(0, 365); self.keep_daily.setValue(self.policy.keep_daily)
            self.keep_weekly = QSpinBox(); self.keep_weekly.setRange(0, 260); self.keep_weekly.setValue(self.policy.keep_weekly)
            self.keep_monthly = QSpinBox(); self.keep_monthly.setRange(0, 120); self.keep_monthly.setValue(self.policy.keep_monthly)
            dest_row = QHBoxLayout(); self.destination = QLineEdit(self.policy.destination); self.destination.setPlaceholderText("Để trống = thư mục sao lưu mặc định")
            browse = QPushButton("Chọn..."); browse.setObjectName("secondary"); browse.clicked.connect(self.choose_destination); dest_row.addWidget(self.destination); dest_row.addWidget(browse)
            form.addRow("", self.backup_enabled); form.addRow("Chu kỳ:", self.interval); form.addRow("Giữ bản theo ngày:", self.keep_daily); form.addRow("Giữ bản theo tuần:", self.keep_weekly); form.addRow("Giữ bản theo tháng:", self.keep_monthly); form.addRow("Thư mục NAS/OneDrive/Drive:", dest_row)
            policy_actions = QHBoxLayout(); save_policy_btn = QPushButton("Lưu chính sách"); save_policy_btn.clicked.connect(self.save_backup_policy)
            auto_now = QPushButton("Chạy sao lưu tự động ngay"); auto_now.setObjectName("secondary"); auto_now.clicked.connect(lambda: self.backup(kind="auto"))
            policy_actions.addWidget(save_policy_btn); policy_actions.addWidget(auto_now); policy_actions.addStretch(); form.addRow("", policy_actions)
            self.backup_health = QLabel(); self.backup_health.setWordWrap(True); form.addRow("Trạng thái:", self.backup_health)
            root.addWidget(policy_box)
            backup_box = QGroupBox("Danh sách bản sao lưu"); bl = QVBoxLayout(backup_box)
            self.backup_model = DictTableModel(columns=[("name", "Tên file"), ("kind_label", "Loại"), ("created_at", "Thời điểm"), ("size_label", "Dung lượng")])
            self.backup_table = QTableView(); self.backup_table.setModel(self.backup_model); self.backup_table.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows); self.backup_table.setSelectionMode(QTableView.SelectionMode.SingleSelection); self.backup_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch); bl.addWidget(self.backup_table)
            br = QHBoxLayout(); manual = QPushButton("Sao lưu ngay"); manual.clicked.connect(self.backup); verify = QPushButton("Kiểm tra toàn vẹn"); verify.setObjectName("secondary"); verify.clicked.connect(self.verify_selected_backup)
            restore = QPushButton("Phục hồi bản đã chọn"); restore.setObjectName("danger"); restore.clicked.connect(self.restore_selected_backup); refresh = QPushButton("Làm mới"); refresh.setObjectName("secondary"); refresh.clicked.connect(self.refresh_backups)
            for w in (manual, verify, restore, refresh): br.addWidget(w)
            br.addStretch(); bl.addLayout(br); root.addWidget(backup_box, 1)
        else:
            box = QGroupBox("Sao lưu trên máy chủ"); layout = QHBoxLayout(box); manual = QPushButton("Yêu cầu máy chủ sao lưu ngay"); manual.clicked.connect(self.backup); layout.addWidget(manual); layout.addStretch(); root.addWidget(box)
        update_box = QGroupBox("Cập nhật ứng dụng"); update_layout = QVBoxLayout(update_box)
        self.update_status = QLabel("Bấm kiểm tra để đọc phiên bản mới."); self.update_status.setWordWrap(True); update_layout.addWidget(self.update_status)
        self.update_button = QPushButton("Kiểm tra cập nhật"); self.update_button.clicked.connect(lambda: self.check_update(silent=False)); ur = QHBoxLayout(); ur.addWidget(self.update_button); ur.addStretch(); update_layout.addLayout(ur); root.addWidget(update_box)
        if not config.is_workstation: self.refresh_backups()

    def choose_destination(self):
        path = QFileDialog.getExistingDirectory(self, "Chọn thư mục sao lưu", self.destination.text() or str(local_core.BACKUP_DIR))
        if path: self.destination.setText(path)

    def save_backup_policy(self):
        self.policy.enabled = self.backup_enabled.isChecked(); self.policy.interval_hours = self.interval.value(); self.policy.keep_daily = self.keep_daily.value(); self.policy.keep_weekly = self.keep_weekly.value(); self.policy.keep_monthly = self.keep_monthly.value(); self.policy.destination = self.destination.text().strip()
        try: backup_manager.save_policy(self.policy); backup_manager.prune_backups(self.policy); self.refresh_backups(); QMessageBox.information(self, "Đã lưu", "Đã lưu chính sách sao lưu.")
        except Exception as exc: QMessageBox.critical(self, "Không thể lưu", str(exc))

    def backup(self, checked=False, kind="manual"):
        server = self.server_controller.httpd if self.server_controller and self.server_controller.httpd else None
        try:
            if server: server.backup_in_progress = True
            if self.config.is_workstation: path = core.create_backup()
            else: path = backup_manager.create_backup(local_core.DB_PATH, kind=kind, policy=self.policy)
            QMessageBox.information(self, "Đã sao lưu", str(path))
            if not self.config.is_workstation: self.refresh_backups()
        except Exception as exc: QMessageBox.critical(self, "Không thể sao lưu", str(exc))
        finally:
            if server: server.backup_in_progress = False

    def refresh_backups(self):
        if self.config.is_workstation: return
        try:
            rows = backup_manager.list_backups(self.policy)
            health = backup_manager.backup_health(self.policy)
            self.backup_health.setText(health["message"])
            self.backup_health.setStyleSheet("color: #b42318; font-weight: 700;" if health["overdue"] else "color: #18794e; font-weight: 700;")
        except Exception as exc:
            rows = []
            self.backup_health.setText(f"Không truy cập được thư mục sao lưu: {exc}")
            self.backup_health.setStyleSheet("color: #b42318; font-weight: 700;")
        labels = {"manual": "Thủ công", "auto": "Tự động", "before": "Trước thao tác", "before_restore": "Trước phục hồi"}
        for row in rows:
            row["kind_label"] = labels.get(row.get("kind"), row.get("kind")); row["size_label"] = f"{int(row.get('size', 0))/1024/1024:.2f} MB"
        self.backup_model.set_data(rows)

    def selected_backup(self):
        indexes = self.backup_table.selectionModel().selectedRows()
        if not indexes: QMessageBox.information(self, "Chưa chọn", "Hãy chọn một bản sao lưu."); return None
        return self.backup_model.record_at(indexes[0].row())

    def verify_selected_backup(self):
        item = self.selected_backup()
        if not item: return
        result = backup_manager.verify_backup(item["path"])
        (QMessageBox.information if result.get("ok") else QMessageBox.critical)(self, "Kiểm tra bản sao lưu", f"{result.get('message')}\nSố bảng: {result.get('tables', 0)}")

    def restore_selected_backup(self):
        item = self.selected_backup()
        if not item: return
        if QMessageBox.question(self, "Xác nhận phục hồi", "Phục hồi CSDL từ bản đã chọn? CSDL hiện tại sẽ được sao lưu an toàn trước khi thay thế.") != QMessageBox.StandardButton.Yes: return
        was_running = bool(self.server_controller and self.server_controller.running)
        try:
            if was_running: self.server_controller.stop()
            result = backup_manager.restore_backup(item["path"], local_core.DB_PATH, self.policy)
            local_core.init_db()
            if was_running: self.server_controller.start()
            QMessageBox.information(self, "Phục hồi thành công", f"Đã phục hồi từ {result['restored_from']}\nBản an toàn: {result['safety_backup']}")
            self.refresh_backups()
            if self.after_restore: self.after_restore()
        except Exception as exc:
            if was_running and self.server_controller and not self.server_controller.running:
                try: self.server_controller.start()
                except Exception: pass
            QMessageBox.critical(self, "Không thể phục hồi", str(exc))

    def refresh(self):
        if not self.config.is_workstation: self.refresh_backups()

    def check_update(self, silent: bool = False):
        self.update_button.setEnabled(False); self.update_status.setText("Đang kiểm tra phiên bản trên Google Drive..."); QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try: info = update_manager.fetch_manifest()
        except Exception as exc:
            self.update_status.setText(f"Không kiểm tra được cập nhật: {exc}")
            if not silent: QMessageBox.warning(self, "Không kiểm tra được cập nhật", str(exc))
            return
        finally: QApplication.restoreOverrideCursor(); self.update_button.setEnabled(True)
        if not update_manager.is_newer_version(info.version, core.VERSION):
            self.update_status.setText(f"Đang dùng phiên bản mới nhất: {core.VERSION}.")
            if not silent: QMessageBox.information(self, "Không có bản mới", f"Phiên bản hiện tại: {core.VERSION}")
            return
        self.update_status.setText(f"Có phiên bản {info.version}: {info.notes or 'Không có ghi chú.'}")
        answer = QMessageBox.question(self, "Có bản cập nhật mới", f"Phiên bản hiện tại: {core.VERSION}\nPhiên bản mới: {info.version}\n\n{info.notes or 'Không có ghi chú phát hành.'}\n\nỨng dụng sẽ sao lưu CSDL, tải gói cập nhật, tự đóng rồi mở lại. Tiếp tục?")
        if answer != QMessageBox.StandardButton.Yes: return
        try:
            backup_path = core.create_backup(); cache_dir = core.UPDATE_CACHE_DIR; zip_path = cache_dir / info.file_name
            progress = QProgressDialog("Đang tải bản cập nhật từ Google Drive...", "Hủy", 0, 100, self); progress.setWindowTitle("Cập nhật ứng dụng"); progress.setWindowModality(Qt.WindowModality.WindowModal); progress.setMinimumDuration(0)
            def on_progress(downloaded, total):
                if progress.wasCanceled(): raise update_manager.UpdateError("Đã hủy tải bản cập nhật.")
                if total: progress.setMaximum(100); progress.setValue(min(99, int(downloaded * 100 / total)))
                else: progress.setMaximum(0)
                QApplication.processEvents()
            update_manager.download_drive_file(info.release_file_id, zip_path, on_progress, timeout=180); progress.setLabelText("Đang kiểm tra tính toàn vẹn của gói cập nhật..."); progress.setMaximum(0); QApplication.processEvents(); update_manager.verify_download(zip_path, info.sha256); progress.close()
            self.update_status.setText(f"Đã tải phiên bản {info.version}. CSDL đã sao lưu tại {backup_path.name}."); update_manager.launch_update_and_exit(zip_path, core.BASE_DIR, info.package_root); QApplication.quit()
        except Exception as exc:
            try: progress.close()
            except Exception: pass
            self.update_status.setText(f"Cập nhật chưa hoàn tất: {exc}"); QMessageBox.critical(self, "Không thể cập nhật", str(exc))


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
        self.settings = SettingsTab(config, self.refresh_all, self.server_controller)
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
        self.connection_label = QLabel()
        self.statusBar().addPermanentWidget(self.connection_label)
        self.statusBar().showMessage(f"Chế độ: {mode_label(config.mode)} — Dữ liệu: {core.DB_PATH}")
        QTimer.singleShot(1800, lambda: self.settings.check_update(silent=True))
        if self.server_tab:
            QTimer.singleShot(500, self.server_tab.auto_start_server)
        if self.config.is_workstation:
            self.connection_timer = QTimer(self); self.connection_timer.timeout.connect(self.update_connection_status); self.connection_timer.start(5000)
            QTimer.singleShot(200, self.update_connection_status)
        else:
            self.connection_label.setText("CSDL cục bộ")
            self.backup_timer = QTimer(self); self.backup_timer.timeout.connect(self.run_auto_backup); self.backup_timer.start(10 * 60 * 1000)
            QTimer.singleShot(2500, self.run_auto_backup)

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

    def update_connection_status(self):
        if not self.config.is_workstation: return
        try:
            import remote_core
            info = remote_core.health()
            readonly = " — chỉ đọc khi server sao lưu" if info.get("read_only") else ""
            self.connection_label.setText(f"● Đã kết nối {info.get('server_name') or info.get('lan_ip')}:{info.get('port')}{readonly}")
            self.connection_label.setStyleSheet("color: #18794e; font-weight: 700;")
        except Exception:
            self.connection_label.setText("● Mất kết nối — đang tự thử lại")
            self.connection_label.setStyleSheet("color: #b42318; font-weight: 700;")

    def run_auto_backup(self):
        if self.config.is_workstation: return
        server = self.server_controller.httpd if self.server_controller and self.server_controller.httpd else None
        try:
            if server: server.backup_in_progress = True
            path = backup_manager.auto_backup_if_due(local_core.DB_PATH)
            if path:
                self.statusBar().showMessage(f"Đã sao lưu tự động: {path.name}", 10000)
                self.settings.refresh_backups()
            else:
                health = backup_manager.backup_health()
                if health.get("overdue"):
                    self.statusBar().showMessage(f"Cảnh báo sao lưu: {health.get('message')}", 15000)
        except Exception as exc:
            self.statusBar().showMessage(f"Sao lưu tự động lỗi: {exc}", 15000)
        finally:
            if server: server.backup_in_progress = False

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
            try:
                servers = remote_core.discover_servers(timeout=1.5)
                if len(servers) == 1:
                    config.server_url = str(servers[0]["url"]); save_config(config); remote_core.health()
                else:
                    raise exc
            except Exception:
                answer = QMessageBox.question(None, "Chưa kết nối được máy chủ", f"{exc}\n\nMở cấu hình hoặc tự dò máy chủ?")
                if answer != QMessageBox.StandardButton.Yes: return 1
                dialog = WorkstationConnectionDialog(config)
                if dialog.exec() != QDialog.DialogCode.Accepted: return 1
                try: remote_core.health()
                except Exception as retry_exc: QMessageBox.critical(None, "Không kết nối được", str(retry_exc)); return 1
    else:
        local_core.init_db()
    window = MainWindow(config)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
