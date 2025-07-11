import sys
import os
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QLineEdit, QPushButton, QGroupBox, QMessageBox, QFileDialog,
    QComboBox
)
from PyQt6.QtCore import QTimer, Qt, pyqtSignal
from PyQt6.QtGui import QPalette, QColor

from datetime import datetime
import csv
import re
import numpy as np

try:
    from Src.Pump_Control import SimdosPump
    from Src.Pump_Control_Fake import FakeSimdosPump
    from Src.PowerMeter_Control import GPM8213PowerMeter
    from Src.Arduino import ArduinoControl
except ImportError:
    print("Warning: Could not import from Src. Trying to adjust sys.path.")
    current_script_path_for_import = os.path.dirname(os.path.abspath(__file__))
    src_module_path_for_import = os.path.join(current_script_path_for_import, "Src")
    src_path_in_sys_path_for_import = False
    for path_entry_for_import in sys.path:
        try:
            if os.path.exists(path_entry_for_import) and os.path.exists(src_module_path_for_import) and \
               os.path.samefile(os.path.abspath(path_entry_for_import), os.path.abspath(src_module_path_for_import)):
                src_path_in_sys_path_for_import = True
                break
        except FileNotFoundError: continue
        except Exception: continue
    if not src_path_in_sys_path_for_import and os.path.isdir(src_module_path_for_import):
        sys.path.insert(0, src_module_path_for_import)
        print(f"Added '{src_module_path_for_import}' to sys.path for module resolution.")
    elif not os.path.isdir(src_module_path_for_import):
         print(f"Warning: Module directory '{src_module_path_for_import}' not found.")


# 디버깅용
DEBUG_WITHOUT_PUMP = False

DEFAULT_PUMP_CONFIGS = {
    "Pump_A": {"port": "COM6", "address": "00", "model": "SIMDOS10", "flow_rate": "30000"},
    "Pump_B": {"port": "COM7", "address": "00", "model": "SIMDOS10", "flow_rate": "30000"}
}
DEFAULT_PUMP_LOG_PATH = r"C:\Data\Pump_Logs"
DEFAULT_POWER_METER_LOG_PATH = r"C:\Data\Power_Meter_Logs"
DEFAULT_POWER_METER_PORT = 'COM5'
DEFAULT_AUTO_CSV_DIR = r"C:\Users\ECHEM\Desktop\Oscar\Backup"
DEFAULT_ARDUINO_PORT = 'COM4'

FARADAY_CONSTANT = 96485.3
GAS_CONSTANT_R = 8.314472
ELECTROLYTE_CONCENTRATION_MOLAR = 1.7
ELECTROLYTE_CONCENTRATION_MOL_PER_UL = ELECTROLYTE_CONCENTRATION_MOLAR * 1E-6

class PumpControlWidget(QWidget):
    connection_status_changed = pyqtSignal(bool)

    def __init__(self, pump_name, default_config):
        super().__init__()
        self.pump_name = pump_name
        self.default_config = default_config
        self.pump_instance = None
        self.connected = False
        self.current_mode_str = "N/A"
        self.is_pump_logging_active = False
        self.init_ui()
        self.update_timer = QTimer(self)
        self.update_timer.timeout.connect(self.update_pump_status_and_log_locally)
        self.update_timer_interval = 500

    def init_ui(self):
        main_layout = QVBoxLayout(self)
        group_box = QGroupBox(self.pump_name)
        main_layout.addWidget(group_box)
        layout = QGridLayout()
        group_box.setLayout(layout)
        layout.addWidget(QLabel("COM Port:"), 0, 0)
        self.port_edit = QLineEdit(self.default_config.get("port", ""))
        layout.addWidget(self.port_edit, 0, 1)
        self.connect_button = QPushButton("Connect")
        self.connect_button.clicked.connect(self.handle_connect_pump)
        layout.addWidget(self.connect_button, 0, 2, 1, 2)
        layout.addWidget(QLabel("Status:"), 1, 0)
        self.status_label = QLabel("Disconnected")
        self.status_label.setStyleSheet("font-weight: bold;")
        self._set_status_color(False)
        layout.addWidget(self.status_label, 1, 1)
        layout.addWidget(QLabel("Model:"), 1, 2)
        self.model_label = QLabel("N/A")
        layout.addWidget(self.model_label, 1, 3)
        layout.addWidget(QLabel("Current Mode:"), 2, 0)
        self.current_mode_label = QLabel("N/A")
        layout.addWidget(self.current_mode_label, 2, 1)
        layout.addWidget(QLabel("Motor Status:"), 2, 2)
        self.motor_status_label = QLabel("N/A")
        layout.addWidget(self.motor_status_label, 2, 3)
        self.start_button = QPushButton("Start Pump")
        self.start_button.clicked.connect(self.handle_start_pump)
        layout.addWidget(self.start_button, 3, 0)
        self.stop_button = QPushButton("Stop Pump")
        self.stop_button.clicked.connect(self.handle_stop_pump)
        layout.addWidget(self.stop_button, 3, 1)
        self.set_run_mode_button = QPushButton("Set to Run Mode")
        self.set_run_mode_button.clicked.connect(self.handle_set_run_mode)
        layout.addWidget(self.set_run_mode_button, 3, 2)
        self.prime_button = QPushButton("Prime (1 stroke)")
        self.prime_button.clicked.connect(self.handle_prime_pump)
        layout.addWidget(self.prime_button, 3, 3)
        layout.addWidget(QLabel("Set Flow Rate (µl/min):"), 4, 0)
        self.flow_rate_set_edit = QLineEdit(self.default_config.get("flow_rate", "30000"))
        layout.addWidget(self.flow_rate_set_edit, 4, 1)
        self.set_flow_rate_button = QPushButton("Set Flow Rate")
        self.set_flow_rate_button.clicked.connect(self.handle_set_flow_rate)
        layout.addWidget(self.set_flow_rate_button, 4, 2, 1, 2)
        layout.addWidget(QLabel("Current Set Rate:"), 5, 0)
        self.current_flow_rate_label = QLabel("N/A µl/min")
        layout.addWidget(self.current_flow_rate_label, 5, 1, 1, 3)
        self.pump_log_status_label = QLabel("Logging: Inactive")
        self.pump_log_status_label.setStyleSheet("font-style: italic;")
        layout.addWidget(self.pump_log_status_label, 6, 0, 1, 4)
        self.message_label = QLabel("")
        self.message_label.setWordWrap(True)
        layout.addWidget(self.message_label, 7,0,1,4)
        self._update_ui_for_connection_state()

    def _set_status_color(self, connected_bool):
        palette = self.status_label.palette()
        palette.setColor(QPalette.ColorRole.WindowText, QColor("green" if connected_bool else "red"))
        self.status_label.setPalette(palette)

    def _update_ui_for_connection_state(self):
        is_connected = self.connected
        self.port_edit.setEnabled(not is_connected)
        self.connect_button.setText("Disconnect" if is_connected else "Connect")
        for widget in [self.start_button, self.stop_button, self.set_run_mode_button,
                       self.prime_button, self.flow_rate_set_edit, self.set_flow_rate_button]:
            widget.setEnabled(is_connected)
        self.pump_log_status_label.setText(f"Logging: {'Active' if self.is_pump_logging_active else 'Inactive'}")
        if not is_connected: self.pump_log_status_label.setText("Logging: Inactive")

    def display_message(self, message, is_error=False):
        self.message_label.setText(message)
        self.message_label.setStyleSheet("color: red;" if is_error else "color: black;")

    def start_actual_pump_logging(self, base_log_path):
        if not (self.pump_instance and self.connected):
            self.display_message("Pump not connected.",is_error=True); return False
        self.pump_instance.base_log_path = base_log_path
        current_set_rate_str = "UnknownRate"
        flow_rate_val = self.pump_instance.get_flow_rate_run_mode()
        if isinstance(flow_rate_val, int): current_set_rate_str = str(flow_rate_val)
        elif self.flow_rate_set_edit.text().isdigit(): current_set_rate_str = self.flow_rate_set_edit.text()
        filename_prefix = f"FlowLog_{self.pump_name}_Rate{current_set_rate_str}"
        if self.pump_instance.start_flow_logging(filename_prefix=filename_prefix):
            self.is_pump_logging_active = True
            self.display_message(f"Pump logging started to {self.pump_instance.base_log_path}",is_error=False)
            self._update_ui_for_connection_state(); return True
        else:
            self.is_pump_logging_active = False
            self.display_message("Failed to start pump logging.",is_error=True)
            self._update_ui_for_connection_state(); return False

    def stop_actual_pump_logging(self):
        if self.pump_instance and self.is_pump_logging_active:
            self.pump_instance.stop_flow_logging()
            self.is_pump_logging_active = False
            self.display_message("Pump logging stopped.",is_error=False)
            self._update_ui_for_connection_state(); return True
        return False

    def handle_connect_pump(self):
        if not self.connected:
            port = self.port_edit.text()
            if not port: self.display_message("COM Port must be entered.",is_error=True); return
            if 'SimdosPump' not in globals():
                self.display_message("Pump_Control module not loaded correctly.", is_error=True)
                QMessageBox.critical(self.window(), "Module Error", "SimdosPump class not found. Cannot connect pump.")
                return

            if DEBUG_WITHOUT_PUMP:
                globals()['FakeSimdosPump'] = FakeSimdosPump
                self.pump_instance = FakeSimdosPump(port=port, pump_address=self.default_config.get("address", "00"),
                    pump_model=self.default_config.get("model", "SIMDOS10"), timeout=0.5,
                    base_log_path=self.default_config.get("default_log_path", "."))
            else:
                self.pump_instance = SimdosPump(port=port, pump_address=self.default_config.get("address", "00"),
                    pump_model=self.default_config.get("model", "SIMDOS10"), timeout=0.5,
                    base_log_path=self.default_config.get("default_log_path", "."))

            self.display_message(f"Connecting to {self.pump_name} on {port}...")
            QApplication.processEvents()
            if self.pump_instance.connect():
                self.connected = True; self.status_label.setText("Connected"); self._set_status_color(True)
                self.display_message(f"{self.pump_name} connection successful.",is_error=False)
                model_fw = self.pump_instance.get_pump_model_firmware()
                self.model_label.setText(model_fw if model_fw and model_fw not in ["ACK", "NACK"] else "Read Error")
                self.update_pump_status_and_log_locally(); self.update_timer.start(self.update_timer_interval)
            else:
                self.status_label.setText("Connection Failed"); self._set_status_color(False)
                self.display_message(f"{self.pump_name} connection failed.",is_error=True); self.pump_instance = None
        else:
            if self.is_pump_logging_active and self.pump_instance: self.pump_instance.stop_flow_logging()
            if self.pump_instance: self.pump_instance.stop_pump(); self.pump_instance.disconnect()
            self.connected = False; self.pump_instance = None; self.status_label.setText("Disconnected")
            self._set_status_color(False)
            for label in [self.model_label, self.current_mode_label, self.motor_status_label, self.current_flow_rate_label]: label.setText("N/A")
            self.update_timer.stop(); self.display_message(f"{self.pump_name} disconnected.",is_error=False)
        self._update_ui_for_connection_state()
        main_window = self.window()
        self.connection_status_changed.emit(self.connected)

        if isinstance(main_window, MainWindow) and main_window.auto_flow_control_active:
            QMessageBox.warning(
                main_window,
                "Automatic Control Stopped",
                f"{self.pump_name} has been disconnected.\n\n"
                "To prevent errors, Automatic Flow Control will now be stopped."
            )
            main_window._toggle_auto_control()

    def handle_start_pump(self):
        if self.pump_instance and self.connected:
            response = self.pump_instance.start_pump()
            self.display_message(f"{self.pump_name} {'started.' if response == 'ACK' else f'start failed (Resp: {response}).'}",is_error=(response != 'ACK'))
            self.update_pump_status_and_log_locally()
        else: self.display_message("Pump not connected.",is_error=True)

    def handle_stop_pump(self):
        if self.pump_instance and self.connected:
            response = self.pump_instance.stop_pump()
            self.display_message(f"{self.pump_name} {'stopped.' if response == 'ACK' else f'stop failed (Resp: {response}).'}",is_error=(response != 'ACK'))
            self.update_pump_status_and_log_locally()
        else: self.display_message("Pump not connected.",is_error=True)

    def handle_set_run_mode(self):
        if self.pump_instance and self.connected:
            response = self.pump_instance.set_mode(0)
            self.display_message(f"{self.pump_name} set to 'Run Mode'.",is_error=False) if response=="ACK" else self.display_message(f"{self.pump_name} 'Run Mode' set failed (Resp: {response}).",is_error=True)
            self.update_pump_status_and_log_locally()
        else: self.display_message("Pump not connected.",is_error=True)

    def handle_prime_pump(self):
        if self.pump_instance and self.connected:
            self.display_message(f"{self.pump_name} priming...",is_error=False); QApplication.processEvents()
            response = self.pump_instance.prime_pump(strokes=1)
            self.display_message(f"{self.pump_name} {'prime complete.' if response else 'prime failed.'}",is_error=(not response))
            self.update_pump_status_and_log_locally()
        else: self.display_message("Pump not connected.",is_error=True)

    def handle_set_flow_rate(self):
        if self.pump_instance and self.connected:
            if self.current_mode_str != "0":
                 reply = QMessageBox.warning(self, "Mode Confirmation",
                                          f"{self.pump_name} is not in 'Run Mode' (Current: Mode {self.current_mode_str}).\n"
                                          "Setting flow rate will change the configuration for 'Run Mode'.\n"
                                          "Do you want to continue? (It's recommended to use 'Set to Run Mode' first).",
                                          QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                          QMessageBox.StandardButton.No)
                 if reply == QMessageBox.StandardButton.No:
                     self.display_message(f"{self.pump_name}: Flow rate setting cancelled (mode check).", is_error=False)
                     return
            try:
                flow_rate_str = self.flow_rate_set_edit.text()
                flow_rate_ul_min = int(flow_rate_str)

                if not (0 <= flow_rate_ul_min <= 99999999):
                    self.display_message(f"{self.pump_name}: Flow rate ({flow_rate_ul_min}) is outside protocol range (0-99,999,999 µl/min). NOT SET.", is_error=True)
                    return

                limits = self.pump_instance.current_pump_limits
                if limits:
                    original_rate = flow_rate_ul_min
                    flow_rate_ul_min = max(limits["min"], min(original_rate, limits["max"]))

                    if original_rate != flow_rate_ul_min:
                        self.display_message(
                            f"{self.pump_name}: Flow rate ({original_rate}) is outside range. Adjusted to {flow_rate_ul_min} µl/min.",
                            is_error=False)

                response = self.pump_instance.set_flow_rate_run_mode(flow_rate_ul_min)
                if response == "ACK":
                    self.display_message(f"{self.pump_name} flow rate set to {flow_rate_ul_min} µl/min.", is_error=False)
                else:
                    self.display_message(f"{self.pump_name} flow rate set failed (Resp: {response}).", is_error=True)
                self.update_pump_status_and_log_locally()
            except ValueError:
                self.display_message("Invalid flow rate value or value out of pump protocol limits.", is_error=True)
            except Exception as e:
                self.display_message(f"Error setting flow rate: {e}", is_error=True)
        else:
            self.display_message("Pump not connected.", is_error=True)

    def update_pump_status_and_log_locally(self):
        if self.pump_instance and self.connected:
            mode_val_raw = self.pump_instance.get_mode(); self.current_mode_str = mode_val_raw
            mode_map = {"0": "Run Mode (0)", "1": "Dispense Vol/Time (1)", "2": "Dispense Rate/Time (2)"}
            self.current_mode_label.setText(mode_map.get(mode_val_raw, f"Read Error ({mode_val_raw})" if mode_val_raw in ["NACK", None] else f"Unknown ({mode_val_raw})"))
            op_status_str = self.pump_instance.get_pump_status(1)
            motor_display_text = "N/A"; motor_style_sheet = "color: black;"
            if op_status_str and op_status_str not in ["ACK", "NACK", None]:
                try:
                    motor_display_text = "Running" if (int(op_status_str) & 1) == 1 else "Stopped"
                    motor_style_sheet = "color: green; font-weight: bold;" if (int(op_status_str) & 1) == 1 else "color: red; font-weight: bold;"
                except ValueError: motor_display_text = "Status Parse Err"; motor_style_sheet = "color: orange;"
            elif op_status_str in ["NACK", None]: motor_display_text = f"Read Error ({op_status_str})"; motor_style_sheet = "color: orange;"
            self.motor_status_label.setText(motor_display_text); self.motor_status_label.setStyleSheet(motor_style_sheet)
            flow_rate = self.pump_instance.get_flow_rate_run_mode()
            if isinstance(flow_rate, int): self.current_flow_rate_label.setText(f"{flow_rate} µl/min")
            elif flow_rate == "NACK": self.current_flow_rate_label.setText("NACK Received")
            elif flow_rate is None: self.current_flow_rate_label.setText("Read Error")
            else: self.current_flow_rate_label.setText(f"{flow_rate}")
            if self.is_pump_logging_active: self.pump_instance.log_one_flow_reading()

    def closeEvent(self, event):
        print(f"Closing {self.pump_name} widget...")
        if self.is_pump_logging_active and self.pump_instance and self.connected: self.pump_instance.stop_flow_logging()
        if self.pump_instance and self.connected: self.pump_instance.stop_pump(); self.pump_instance.disconnect()
        self.update_timer.stop(); super().closeEvent(event)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Pump & Power Meter Controller")

        # --- 인스턴스 변수 초기화 ---
        self.power_meter_instance = None
        self.is_power_meter_connected = False
        self.is_master_logging_active = False
        self.arduino_instance = None
        self.is_arduino_connected = False

        self.auto_flow_control_active = False
        self.auto_flow_timer = QTimer(self)
        self.auto_flow_timer.timeout.connect(self._auto_update_flow_rate)

        # --- 타이머 초기화 ---
        self.power_meter_update_timer = QTimer(self)
        self.power_meter_update_timer.timeout.connect(self.update_power_meter_status_and_log)
        self.power_meter_update_interval = 500
        
        self.arduino_update_timer = QTimer(self)
        self.arduino_update_timer.timeout.connect(self.update_arduino_status)
        self.arduino_update_interval = 2000

        # --- 메인 UI 설정 ---
        self.init_ui()
        
        # --- 시그널 연결 ---
        self.pump_a_widget.connection_status_changed.connect(self._update_master_pump_buttons_state)
        self.pump_b_widget.connection_status_changed.connect(self._update_master_pump_buttons_state)
        
        # --- 초기 UI 상태 설정 ---
        self._update_master_pump_buttons_state()
        self._update_master_logging_ui()

    def init_ui(self):
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        top_layout = QVBoxLayout(main_widget)

        # --- 1. 통합 로깅 제어 섹션 ---
        master_log_group = QGroupBox("Master Logging Control")
        master_log_layout = QGridLayout()
        master_log_group.setLayout(master_log_layout)
        master_log_layout.addWidget(QLabel("Pumps Log Path:"), 0, 0)
        self.global_pump_log_path_edit = QLineEdit(DEFAULT_PUMP_LOG_PATH)
        master_log_layout.addWidget(self.global_pump_log_path_edit, 0, 1)
        self.browse_global_pump_log_path_button = QPushButton("Browse...")
        self.browse_global_pump_log_path_button.clicked.connect(lambda: self._browse_log_path(self.global_pump_log_path_edit))
        master_log_layout.addWidget(self.browse_global_pump_log_path_button, 0, 2)
        master_log_layout.addWidget(QLabel("PM Log Path:"), 1, 0)
        self.global_pm_log_path_edit = QLineEdit(DEFAULT_POWER_METER_LOG_PATH)
        master_log_layout.addWidget(self.global_pm_log_path_edit, 1, 1)
        self.browse_global_pm_log_path_button = QPushButton("Browse...")
        self.browse_global_pm_log_path_button.clicked.connect(lambda: self._browse_log_path(self.global_pm_log_path_edit))
        master_log_layout.addWidget(self.browse_global_pm_log_path_button, 1, 2)
        self.master_toggle_logging_button = QPushButton("Start All Logging")
        self.master_toggle_logging_button.clicked.connect(self.handle_master_toggle_logging)
        master_log_layout.addWidget(self.master_toggle_logging_button, 0, 3, 2, 1)
        self.master_toggle_logging_button.setFixedHeight(50)
        top_layout.addWidget(master_log_group)

        # --- 2. 펌프 제어 섹션 ---
        pumps_group = QGroupBox("Pump Controls")
        pumps_main_layout = QVBoxLayout()
        pumps_group.setLayout(pumps_main_layout)
        master_buttons_layout = QHBoxLayout()
        self.master_connect_all_button = QPushButton("🔗 Connect All")
        self.master_connect_all_button.clicked.connect(self.handle_master_connect_all)
        self.master_start_all_button = QPushButton("▶ Start All")
        self.master_start_all_button.clicked.connect(self.handle_master_start_all)
        self.master_stop_all_button = QPushButton("■ Stop All")
        self.master_stop_all_button.clicked.connect(self.handle_master_stop_all)
        master_buttons_layout.addWidget(self.master_connect_all_button)
        master_buttons_layout.addWidget(self.master_start_all_button)
        master_buttons_layout.addWidget(self.master_stop_all_button)
        pumps_main_layout.addLayout(master_buttons_layout)
        pump_widgets_layout = QHBoxLayout()
        self.pump_a_widget = PumpControlWidget("Pump A", DEFAULT_PUMP_CONFIGS["Pump_A"])
        self.pump_b_widget = PumpControlWidget("Pump B", DEFAULT_PUMP_CONFIGS["Pump_B"])
        pump_widgets_layout.addWidget(self.pump_a_widget)
        pump_widgets_layout.addWidget(self.pump_b_widget)
        pumps_main_layout.addLayout(pump_widgets_layout)
        top_layout.addWidget(pumps_group)

        # --- 3. 자동 유량제어 섹션 ---
        auto_flow_group = QGroupBox("Automatic Flow Control")
        auto_flow_layout = QGridLayout()
        auto_flow_group.setLayout(auto_flow_layout)

        auto_flow_layout.addWidget(QLabel("CSV Data Directory:"), 0, 0)
        self.auto_csv_dir_edit = QLineEdit(DEFAULT_AUTO_CSV_DIR)
        auto_flow_layout.addWidget(self.auto_csv_dir_edit, 0, 1, 1, 4)
        self.auto_browse_csv_dir_button = QPushButton("Browse...")
        self.auto_browse_csv_dir_button.clicked.connect(self._auto_browse_csv_dir)
        auto_flow_layout.addWidget(self.auto_browse_csv_dir_button, 0, 5)

        auto_flow_layout.addWidget(QLabel("Ch. for Current (I):"), 1, 0)
        self.auto_channel_no_combo = QComboBox()
        self.auto_channel_no_combo.addItems([str(i) for i in range(1, 9)])
        self.auto_channel_no_combo.setCurrentText("3")
        auto_flow_layout.addWidget(self.auto_channel_no_combo, 1, 1)
        auto_flow_layout.addWidget(QLabel("Ch. for SOC (V):"), 1, 2)
        self.auto_soc_channel_combo = QComboBox()
        self.auto_soc_channel_combo.addItems([str(i) for i in range(1, 9)])
        self.auto_soc_channel_combo.setCurrentText("4")
        auto_flow_layout.addWidget(self.auto_soc_channel_combo, 1, 3)

        auto_flow_layout.addWidget(QLabel("MIN Flow Rate (µl/min):"), 2, 0)
        self.auto_min_flow_edit = QLineEdit("2640")
        auto_flow_layout.addWidget(self.auto_min_flow_edit, 2, 1)
        auto_flow_layout.addWidget(QLabel("MAX Flow Rate (µl/min):"), 2, 2)
        self.auto_max_flow_edit = QLineEdit("6540")
        auto_flow_layout.addWidget(self.auto_max_flow_edit, 2, 3)

        auto_flow_layout.addWidget(QLabel("Lambda Charge (λ_C):"), 3, 0)
        self.auto_lambda_c_edit = QLineEdit("4.5")
        auto_flow_layout.addWidget(self.auto_lambda_c_edit, 3, 1)
        auto_flow_layout.addWidget(QLabel("Lambda Discharge (λ_D):"), 3, 2)
        self.auto_lambda_d_edit = QLineEdit("4.5")
        auto_flow_layout.addWidget(self.auto_lambda_d_edit, 3, 3)

        auto_flow_layout.addWidget(QLabel("No. of Cells:"), 4, 0)
        self.auto_n_cell_edit = QLineEdit("1")
        auto_flow_layout.addWidget(self.auto_n_cell_edit, 4, 1)
        auto_flow_layout.addWidget(QLabel("Update Interval (s):"), 4, 2)
        self.auto_update_interval_edit = QLineEdit("10")
        auto_flow_layout.addWidget(self.auto_update_interval_edit, 4, 3)

        auto_flow_layout.addWidget(QLabel("Temp Sensors for Avg:"), 5, 0)
        temp_combo_layout = QHBoxLayout() # *** FIX: Layout for combo boxes
        self.temp_sensor_1_combo = QComboBox()
        self.temp_sensor_1_combo.addItems([f"A{i}" for i in range(4)])
        self.temp_sensor_1_combo.setCurrentIndex(0)
        temp_combo_layout.addWidget(self.temp_sensor_1_combo)
        self.temp_sensor_2_combo = QComboBox()
        self.temp_sensor_2_combo.addItems([f"A{i}" for i in range(4)])
        self.temp_sensor_2_combo.setCurrentIndex(1)
        temp_combo_layout.addWidget(self.temp_sensor_2_combo)
        auto_flow_layout.addLayout(temp_combo_layout, 5, 1, 1, 2)

        self.avg_temp_display_label = QLabel("Avg Temp: N/A")
        self.avg_temp_display_label.setStyleSheet("font-weight: bold;")
        auto_flow_layout.addWidget(self.avg_temp_display_label, 5, 3)

        auto_flow_layout.addWidget(QLabel("Real-time SOC:"), 6, 0)
        self.auto_current_soc_display_label = QLabel("N/A")
        self.auto_current_soc_display_label.setStyleSheet("font-weight: bold;")
        auto_flow_layout.addWidget(self.auto_current_soc_display_label, 6, 1, 1, 3)

        self.auto_toggle_control_button = QPushButton("Start Auto Control")
        self.auto_toggle_control_button.clicked.connect(self._toggle_auto_control)
        auto_flow_layout.addWidget(self.auto_toggle_control_button, 7, 0, 1, 6)

        self.auto_control_status_label = QLabel("Status: Inactive.")
        self.auto_control_status_label.setStyleSheet("font-style: italic;")
        auto_flow_layout.addWidget(self.auto_control_status_label, 8, 0, 1, 6)
        
        top_layout.addWidget(auto_flow_group)

        # --- 4. 아두이노 및 파워미터 제어 섹션 ---
        bottom_controls_layout = QHBoxLayout()

        # 4.1 아두이노 제어 그룹
        arduino_group = QGroupBox("Arduino Control")
        arduino_layout = QGridLayout()
        arduino_group.setLayout(arduino_layout)

        arduino_layout.addWidget(QLabel("Arduino COM Port:"), 0, 0)
        self.arduino_port_edit = QLineEdit(DEFAULT_ARDUINO_PORT)
        arduino_layout.addWidget(self.arduino_port_edit, 0, 1)
        self.arduino_connect_button = QPushButton("Connect")
        self.arduino_connect_button.clicked.connect(self.handle_connect_arduino)
        arduino_layout.addWidget(self.arduino_connect_button, 0, 2)
        self.arduino_status_label = QLabel("Status: Disconnected")
        self.arduino_status_label.setStyleSheet("font-weight: bold; color: red;")
        arduino_layout.addWidget(self.arduino_status_label, 0, 3)

        relay_button_layout = QHBoxLayout()
        self.relay_open_button = QPushButton("열림 (Open)")
        self.relay_open_button.clicked.connect(self.handle_open_relay)
        self.relay_open_button.setEnabled(False)
        self.relay_close_button = QPushButton("닫힘 (Close)")
        self.relay_close_button.clicked.connect(self.handle_close_relay)
        self.relay_close_button.setEnabled(False)
        relay_button_layout.addWidget(self.relay_open_button)
        relay_button_layout.addWidget(self.relay_close_button)
        arduino_layout.addLayout(relay_button_layout, 1, 0, 1, 4)

        arduino_layout.addWidget(QLabel("Temperatures (°C):"), 2, 0)
        self.temp_display_labels = []
        temp_labels_layout = QHBoxLayout()
        for i in range(4):
            label = QLabel(f"A{i}: N/A")
            self.temp_display_labels.append(label)
            temp_labels_layout.addWidget(label)
        arduino_layout.addLayout(temp_labels_layout, 2, 1, 1, 3)

        self.arduino_message_label = QLabel("")
        self.arduino_message_label.setWordWrap(True)
        arduino_layout.addWidget(self.arduino_message_label, 3, 0, 1, 4)
        
        bottom_controls_layout.addWidget(arduino_group)

        # 4.2 파워미터 제어 그룹
        pm_group = QGroupBox("Power Meter (GPM-8213)")
        pm_grid_layout = QGridLayout()
        pm_group.setLayout(pm_grid_layout)
        pm_grid_layout.addWidget(QLabel("COM Port:"), 0, 0)
        self.pm_port_edit = QLineEdit(DEFAULT_POWER_METER_PORT)
        pm_grid_layout.addWidget(self.pm_port_edit, 0, 1)
        self.pm_connect_button = QPushButton("Connect")
        self.pm_connect_button.clicked.connect(self.handle_connect_power_meter)
        pm_grid_layout.addWidget(self.pm_connect_button, 0, 2)
        self.pm_status_label = QLabel("Status: Disconnected")
        self.pm_status_label.setStyleSheet("font-weight: bold; color: red;")
        pm_grid_layout.addWidget(self.pm_status_label, 0, 3)
        pm_grid_layout.addWidget(QLabel("Current Power (W):"), 1, 0)
        self.pm_current_power_label = QLabel("N/A")
        pm_grid_layout.addWidget(self.pm_current_power_label, 1, 1)
        pm_grid_layout.addWidget(QLabel("Accumulated Energy (Wh):"), 1, 2)
        self.pm_accumulated_energy_label = QLabel("N/A")
        pm_grid_layout.addWidget(self.pm_accumulated_energy_label, 1, 3)
        self.pm_logging_status_label = QLabel("PM Logging: Inactive")
        self.pm_logging_status_label.setStyleSheet("font-style: italic;")
        pm_grid_layout.addWidget(self.pm_logging_status_label, 2, 0, 1, 4)
        self.pm_message_label = QLabel("")
        self.pm_message_label.setWordWrap(True)
        pm_grid_layout.addWidget(self.pm_message_label, 3, 0, 1, 4)
        
        bottom_controls_layout.addWidget(pm_group)
        
        top_layout.addLayout(bottom_controls_layout)
        self.adjustSize()

    # --- MainWindow의 모든 메소드들 ---

    def handle_connect_arduino(self):
        if not self.is_arduino_connected:
            port = self.arduino_port_edit.text()
            if not port:
                self._arduino_display_message("Arduino COM Port를 입력해야 합니다.", True, 3000)
                return

            if 'ArduinoControl' not in globals():
                QMessageBox.critical(self, "Module Error", "ArduinoControl 클래스를 찾을 수 없습니다.")
                return

            self.arduino_instance = ArduinoControl(port=port)
            self._arduino_display_message(f"Connecting to Arduino on {port}...", False)
            QApplication.processEvents()

            if self.arduino_instance.connect():
                self.is_arduino_connected = True
                self.arduino_status_label.setText("Status: Connected")
                self.arduino_status_label.setStyleSheet("font-weight: bold; color: green;")
                self.arduino_port_edit.setEnabled(False)
                self.arduino_connect_button.setText("Disconnect")
                self.relay_open_button.setEnabled(True)
                self.relay_close_button.setEnabled(True)
                self._arduino_display_message(f"Arduino on {port} connected.", False, 5000)
                self.arduino_update_timer.start(self.arduino_update_interval)
            else:
                self._arduino_display_message(f"Failed to connect to Arduino on {port}.", True, 5000)
                self.arduino_instance = None
        else:
            self.arduino_update_timer.stop()
            if self.arduino_instance:
                self.arduino_instance.disconnect()
            self.is_arduino_connected = False
            self.arduino_instance = None
            self.arduino_status_label.setText("Status: Disconnected")
            self.arduino_status_label.setStyleSheet("font-weight: bold; color: red;")
            self.arduino_port_edit.setEnabled(True)
            self.arduino_connect_button.setText("Connect")
            self.relay_open_button.setEnabled(False)
            self.relay_close_button.setEnabled(False)
            self._arduino_display_message("Arduino disconnected.", False, 5000)
            for label in self.temp_display_labels:
                label.setText(label.text().split(':')[0] + ": N/A")
            self.avg_temp_display_label.setText("Avg Temp: N/A")

    def handle_open_relay(self):
        if self.arduino_instance and self.is_arduino_connected:
            response = self.arduino_instance.open_relay()
            self._arduino_display_message(f"Relay opened. Response: {response}", False, 3000)

    def handle_close_relay(self):
        if self.arduino_instance and self.is_arduino_connected:
            response = self.arduino_instance.close_relay()
            self._arduino_display_message(f"Relay closed. Response: {response}", False, 3000)

    def _arduino_display_message(self, message, is_error=False, duration=0):
        self.arduino_message_label.setText(message)
        self.arduino_message_label.setStyleSheet("color: red;" if is_error else "color: blue;")
        if duration > 0:
            QTimer.singleShot(duration, lambda: self.arduino_message_label.setText(""))

    def update_arduino_status(self):
        if self.arduino_instance and self.is_arduino_connected:
            for i in range(4):
                temp = self.arduino_instance.get_temperature(i)
                if temp is not None:
                    self.temp_display_labels[i].setText(f"A{i}: {temp:.2f}")
                else:
                    self.temp_display_labels[i].setText(f"A{i}: Error")
    
    def handle_connect_power_meter(self):
        if not self.is_power_meter_connected:
            port = self.pm_port_edit.text()
            if not port: self._pm_display_message("Power Meter COM Port must be entered.", True, 5000); return
            if 'GPM8213PowerMeter' not in globals(): QMessageBox.critical(self, "Module Error", "PowerMeter_Control module not loaded correctly."); self._pm_display_message("PowerMeter_Control module not loaded.", True); return
            self._pm_display_message(f"Connecting to Power Meter on {port}..."); QApplication.processEvents()
            self.power_meter_instance = GPM8213PowerMeter(port=port)
            if self.power_meter_instance.connect():
                if self.power_meter_instance.setup_meter():
                    self.is_power_meter_connected = True; self.pm_status_label.setText("Status: Connected"); self.pm_status_label.setStyleSheet("font-weight: bold; color: green;")
                    self.pm_port_edit.setEnabled(False); self.pm_connect_button.setText("Disconnect"); self.power_meter_update_timer.start(self.power_meter_update_interval)
                    self._pm_display_message(f"Power Meter connected successfully ({port}).", False, 5000)
                else:
                    self._pm_display_message("Power Meter setup failed after connection.", True, 5000);
                    if self.power_meter_instance: self.power_meter_instance.disconnect(); self.power_meter_instance = None
            else: self._pm_display_message(f"Failed to connect to Power Meter on {port}. Check port/power.", True, 5000); self.power_meter_instance = None
        else: 
            if self.is_master_logging_active: self._pm_display_message("PM disconnected, stopping master logging.", duration=5000); self.handle_master_toggle_logging() 
            if self.power_meter_instance: self.power_meter_instance.disconnect()
            self.is_power_meter_connected = False; self.power_meter_instance = None; self.pm_status_label.setText("Status: Disconnected"); self.pm_status_label.setStyleSheet("font-weight: bold; color: red;")
            self.pm_port_edit.setEnabled(True); self.pm_connect_button.setText("Connect")
            for label in [self.pm_current_power_label, self.pm_accumulated_energy_label]: label.setText("N/A")
            self.power_meter_update_timer.stop(); self._pm_display_message("Power Meter disconnected.", False, 5000)
        self._update_master_logging_ui()

    def update_power_meter_status_and_log(self):
        if self.power_meter_instance and self.is_power_meter_connected:
            readings = self.power_meter_instance.get_readings() 
            if readings:
                self.pm_current_power_label.setText(f"{readings['power']:.4f} W"); self.pm_accumulated_energy_label.setText(f"{readings['energy_wh']:.4f} Wh")
                if self.is_master_logging_active and self.power_meter_instance.is_pm_logging_active:
                    self.power_meter_instance.log_pm_reading(datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3], readings['voltage'], readings['current'], readings['power'], readings['energy_wh']) 
            else: self.pm_current_power_label.setText("Read Error"); self._pm_display_message("PM read error.", True, 3000)

    def _auto_update_flow_rate(self):
        csv_dir = self.auto_csv_dir_edit.text()
        current_channel_str = self.auto_channel_no_combo.currentText()
        soc_channel_str = self.auto_soc_channel_combo.currentText()
        
        current_mA = self._get_latest_value_from_csv(csv_dir, current_channel_str, "Current(mA)")
        voltage_V_ocv = self._get_latest_value_from_csv(csv_dir, soc_channel_str, "Voltage(V)")

        if current_mA is None or voltage_V_ocv is None:
            return

        try:
            lambda_c = float(self.auto_lambda_c_edit.text())
            lambda_d = float(self.auto_lambda_d_edit.text())
            n_cell = int(self.auto_n_cell_edit.text())
            user_min_flow = int(self.auto_min_flow_edit.text())
            user_max_flow = int(self.auto_max_flow_edit.text())
            if user_min_flow > user_max_flow:
                self._auto_display_status_message("Error: MIN Flow > MAX Flow.", True, 5000)
                return

            temp_ch1_index = self.temp_sensor_1_combo.currentIndex()
            temp_ch2_index = self.temp_sensor_2_combo.currentIndex()

            if temp_ch1_index == temp_ch2_index:
                self._auto_display_status_message("Error: Same sensor selected.", True, 5000)
                self.avg_temp_display_label.setText("Avg Temp: Error")
                return

            temp1 = self.arduino_instance.get_temperature(temp_ch1_index) if self.is_arduino_connected and self.arduino_instance else None
            temp2 = self.arduino_instance.get_temperature(temp_ch2_index) if self.is_arduino_connected and self.arduino_instance else None

            valid_temps = []
            if temp1 is not None: valid_temps.append(temp1)
            if temp2 is not None: valid_temps.append(temp2)

            if not valid_temps:
                self._auto_display_status_message(f"Error: Failed to read sensors.", True, 5000)
                self.avg_temp_display_label.setText("Avg Temp: Error")
                avg_temp_c = 25.0 # Fallback to default
            else:
                avg_temp_c = sum(valid_temps) / len(valid_temps)
                self.avg_temp_display_label.setText(f"Avg Temp: {avg_temp_c:.2f} °C")
            
            temp_k = avg_temp_c + 273.15

        except (ValueError, TypeError):
            self._auto_display_status_message("Error: Invalid numeric input for Auto params.", True, 5000)
            return

        if not (1.3 <= voltage_V_ocv <= 1.5):
            warn_msg = f"Warning: Voltage ({voltage_V_ocv:.3f}V) is outside expected range."
            self._auto_display_status_message(warn_msg, is_error=True, duration=10000)

        current_A = current_mA / 1000.0
        real_soc = self._calculate_soc_from_nernst(voltage_V_ocv, temp_k)
        self.auto_current_soc_display_label.setText(f"{real_soc:.3f} (V:{voltage_V_ocv:.4f})")

        selected_lambda = lambda_c if current_A > 0 else lambda_d
        calculated_flow_ul_min = self._calculate_flow_ul_min(current_A, selected_lambda, n_cell, real_soc, current_A > 0)
        original_calculated_flow = int(round(calculated_flow_ul_min))

        base_msg = f"I:{current_A:.3f}A, V:{voltage_V_ocv:.3f}V -> SOC:{real_soc:.3f}, Flow:{original_calculated_flow}µl/min."
        applied_pumps, failed_pumps_msgs = [], []
        mode_change_warning_shown = False

        pumps_to_try = [("Pump A", self.pump_a_widget), ("Pump B", self.pump_b_widget)]

        for pump_name, pump_widget in pumps_to_try:
            if not (pump_widget and pump_widget.connected and pump_widget.pump_instance):
                continue

            if pump_widget.current_mode_str != "0":
                if not mode_change_warning_shown:
                    QMessageBox.warning(self, "Auto Mode Change", "Pump(s) not in Run Mode. Auto change attempt.")
                    mode_change_warning_shown = True
                response_mode = pump_widget.pump_instance.set_mode(0)
                pump_widget.update_pump_status_and_log_locally()
                if response_mode != "ACK" or pump_widget.current_mode_str != "0":
                    failed_pumps_msgs.append(f"{pump_name}(mode fail)")
                    continue

            if "Running" not in pump_widget.motor_status_label.text():
                pump_widget.display_message(f"Auto-starting {pump_name} for control...", is_error=False)
                start_response = pump_widget.pump_instance.start_pump()
                if start_response != 'ACK':
                    failed_pumps_msgs.append(f"{pump_name}(start fail)")
                    continue

            final_lower_bound = user_min_flow
            final_upper_bound = user_max_flow

            if pump_widget.pump_instance.current_pump_limits:
                pump_hw_min = pump_widget.pump_instance.current_pump_limits["min"]
                pump_hw_max = pump_widget.pump_instance.current_pump_limits["max"]
                final_lower_bound = max(user_min_flow, pump_hw_min)
                final_upper_bound = min(user_max_flow, pump_hw_max)
            
            flow_to_set = int(round(max(final_lower_bound, min(original_calculated_flow, final_upper_bound))))

            if flow_to_set != original_calculated_flow:
                msg = f"Auto: Calc. flow ({original_calculated_flow}) adjusted to {flow_to_set} by limits."
                pump_widget.display_message(msg, is_error=False)

            try:
                response_flow = pump_widget.pump_instance.set_flow_rate_run_mode(flow_to_set)
                if response_flow == "ACK":
                    pump_widget.flow_rate_set_edit.setText(str(flow_to_set))
                    pump_widget.display_message(f"Auto flow: {flow_to_set} µl/min.", False)
                    applied_pumps.append(pump_name)
                else:
                    pump_widget.display_message(f"Auto flow set failed (Resp:{response_flow}).", True)
                    failed_pumps_msgs.append(f"{pump_name}(flow fail)")
            except ValueError as e_protocol:
                pump_widget.display_message(f"Auto flow error: {e_protocol}", True)
                failed_pumps_msgs.append(f"{pump_name}(prot. err)")
            
            pump_widget.update_pump_status_and_log_locally()
    
        final_msg = base_msg
        if applied_pumps: final_msg += f" Applied: {', '.join(applied_pumps)}."
        if failed_pumps_msgs: final_msg += f" Failed: {', '.join(failed_pumps_msgs)}."
        self._auto_display_status_message(final_msg, is_error=bool(failed_pumps_msgs), duration=10000)

    def _pm_display_message(self, message, is_error=False, duration=0):
        self.pm_message_label.setText(message)
        self.pm_message_label.setStyleSheet("color: red;" if is_error else "color: black;")
        if duration > 0:
            QTimer.singleShot(duration, lambda: self.pm_message_label.setText(""))

    def _browse_log_path(self, line_edit_widget):
        directory = QFileDialog.getExistingDirectory(self, "Select Log Directory", line_edit_widget.text())
        if directory: line_edit_widget.setText(directory)
            
    def _update_master_logging_ui(self):
        self.master_toggle_logging_button.setText("Stop All Logging" if self.is_master_logging_active else "Start All Logging")
        path_widgets_enabled = not self.is_master_logging_active
        for widget in [self.global_pump_log_path_edit, self.browse_global_pump_log_path_button,
                       self.global_pm_log_path_edit, self.browse_global_pm_log_path_button]:
            widget.setEnabled(path_widgets_enabled)
        if hasattr(self, 'pump_a_widget') and self.pump_a_widget: 
             self.pump_a_widget.is_pump_logging_active = self.is_master_logging_active
             if self.pump_a_widget.isVisible(): self.pump_a_widget._update_ui_for_connection_state()
        if hasattr(self, 'pump_b_widget') and self.pump_b_widget:
             self.pump_b_widget.is_pump_logging_active = self.is_master_logging_active
             if self.pump_b_widget.isVisible(): self.pump_b_widget._update_ui_for_connection_state()
        self.pm_logging_status_label.setText(f"PM Logging: {'Active' if self.is_master_logging_active and self.is_power_meter_connected else 'Inactive'}")

    def handle_master_toggle_logging(self):
        can_log_anything = (hasattr(self, 'pump_a_widget') and self.pump_a_widget.connected) or \
                           (hasattr(self, 'pump_b_widget') and self.pump_b_widget.connected) or \
                           self.is_power_meter_connected
        if not can_log_anything and not self.is_master_logging_active: 
            QMessageBox.warning(self, "Logging Error", "No devices are connected to start logging from."); return
        if not self.is_master_logging_active: 
            pump_log_path = self.global_pump_log_path_edit.text(); pm_log_path = self.global_pm_log_path_edit.text()
            if not pump_log_path or not pm_log_path: 
                QMessageBox.warning(self, "Path Error", "Log paths must be specified."); return
            for path in [pump_log_path, pm_log_path]:
                if not os.path.exists(path):
                    try: os.makedirs(path); print(f"Created directory: {path}")
                    except OSError as e: QMessageBox.critical(self, "Path Error", f"Error creating dir {path}: {e}"); return
            success_pa, success_pb, success_pm = True, True, True; logged_something = False
            if hasattr(self,'pump_a_widget') and self.pump_a_widget.connected: success_pa=self.pump_a_widget.start_actual_pump_logging(pump_log_path);logged_something|=success_pa
            if hasattr(self,'pump_b_widget') and self.pump_b_widget.connected: success_pb=self.pump_b_widget.start_actual_pump_logging(pump_log_path);logged_something|=success_pb
            if self.is_power_meter_connected and self.power_meter_instance:
                self.power_meter_instance.start_energy_accumulation()
                success_pm = self.power_meter_instance.start_pm_logging(pm_log_path, f"PowerLog_GPM8213_{datetime.now().strftime('%Y%m%d')}"); logged_something|=success_pm
            if not logged_something and can_log_anything: QMessageBox.critical(self, "Logging Error", "Failed to start logging for any connected device."); self.is_master_logging_active = False
            elif success_pa and success_pb and success_pm : self.is_master_logging_active = True; QMessageBox.information(self, "Logging Control", "Master logging started.")
            else: 
                if hasattr(self,'pump_a_widget') and self.pump_a_widget.is_pump_logging_active : self.pump_a_widget.stop_actual_pump_logging()
                if hasattr(self,'pump_b_widget') and self.pump_b_widget.is_pump_logging_active : self.pump_b_widget.stop_actual_pump_logging()
                if self.power_meter_instance and self.power_meter_instance.is_pm_logging_active:
                    self.power_meter_instance.stop_pm_logging()
                    if self.power_meter_instance.is_connected: self.power_meter_instance.stop_energy_accumulation()
                self.is_master_logging_active = False; QMessageBox.critical(self, "Logging Error", "One or more logs failed. Any started logs stopped.")
        else: 
            if hasattr(self,'pump_a_widget') and self.pump_a_widget.pump_instance: self.pump_a_widget.stop_actual_pump_logging()
            if hasattr(self,'pump_b_widget') and self.pump_b_widget.pump_instance: self.pump_b_widget.stop_actual_pump_logging()
            if self.power_meter_instance: self.power_meter_instance.stop_energy_accumulation(); self.power_meter_instance.stop_pm_logging()
            self.is_master_logging_active = False; QMessageBox.information(self, "Logging Control", "Master logging stopped.")
        self._update_master_logging_ui()

    def handle_master_connect_all(self):
        pump_a_connected = hasattr(self, 'pump_a_widget') and self.pump_a_widget.connected
        pump_b_connected = hasattr(self, 'pump_b_widget') and self.pump_b_widget.connected
        all_pumps_connected = pump_a_connected and pump_b_connected
        
        if all_pumps_connected:
            print("Master Control: Disconnecting all pumps...")
            if hasattr(self, 'pump_a_widget'): self.pump_a_widget.handle_connect_pump()
            if hasattr(self, 'pump_b_widget'): self.pump_b_widget.handle_connect_pump()
        else:
            print("Master Control: Attempting to connect all pumps...")
            if hasattr(self, 'pump_a_widget') and not self.pump_a_widget.connected:
                self.pump_a_widget.handle_connect_pump()
            if hasattr(self, 'pump_b_widget') and not self.pump_b_widget.connected:
                self.pump_b_widget.handle_connect_pump()

    def handle_master_start_all(self):
        print("Master Control: Starting all connected pumps...")
        if hasattr(self, 'pump_a_widget') and self.pump_a_widget.connected:
            self.pump_a_widget.handle_start_pump()
        if hasattr(self, 'pump_b_widget') and self.pump_b_widget.connected:
            self.pump_b_widget.handle_start_pump()

    def handle_master_stop_all(self): 
        print("Master Control: Stopping all connected pumps...")
        if self.auto_flow_control_active:
            self._toggle_auto_control()
        if hasattr(self, 'pump_a_widget') and self.pump_a_widget.connected:
            self.pump_a_widget.handle_stop_pump()
        if hasattr(self, 'pump_b_widget') and self.pump_b_widget.connected:
            self.pump_b_widget.handle_stop_pump()

    def _update_master_pump_buttons_state(self):
        pump_a_connected = hasattr(self, 'pump_a_widget') and self.pump_a_widget.connected
        pump_b_connected = hasattr(self, 'pump_b_widget') and self.pump_b_widget.connected
        any_pump_connected = pump_a_connected or pump_b_connected
        all_pumps_connected = pump_a_connected and pump_b_connected
        self.master_start_all_button.setEnabled(any_pump_connected)
        self.master_stop_all_button.setEnabled(any_pump_connected)
        if all_pumps_connected:
            self.master_connect_all_button.setText("🔌 Disconnect All")
        else:
            self.master_connect_all_button.setText("🔗 Connect All")
        self.master_connect_all_button.setEnabled(True)

    def _auto_browse_csv_dir(self):
        directory = QFileDialog.getExistingDirectory(self, "Select CSV Data Directory", self.auto_csv_dir_edit.text())
        if directory: self.auto_csv_dir_edit.setText(directory)
            
    def _auto_display_status_message(self, message, is_error=False, duration=0):
        prefix = "Status: Active. " if self.auto_flow_control_active else "Status: Inactive. "
        self.auto_control_status_label.setText(prefix + message)
        self.auto_control_status_label.setStyleSheet("color: red; font-style: italic;" if is_error else "color: blue; font-style: italic;")
        if duration > 0:
            QTimer.singleShot(duration, lambda: (
                self.auto_control_status_label.setText("Status: Active." if self.auto_flow_control_active else "Status: Inactive."),
                self.auto_control_status_label.setStyleSheet("font-style: italic;")
            ))

    def _get_latest_value_from_csv(self, directory_path, channel_str, column_name):
        if not os.path.isdir(directory_path): 
            self._auto_display_status_message(f"Err: CSV Dir not found: {directory_path}", True, 5000)
            return None
        
        file_prefix = f"Data-24-{channel_str} "
        latest_file_path = None
        latest_datetime_obj = None
        datetime_pattern = re.compile(r"(\d{4}-\d{2}-\d{2} \d{2}-\d{2}-\d{2})")
        
        try:
            for filename in os.listdir(directory_path):
                if filename.startswith(file_prefix) and filename.endswith(".csv"):
                    match = datetime_pattern.search(filename)
                    if match:
                        current_file_datetime_obj = datetime.strptime(match.group(1), "%Y-%m-%d %H-%M-%S")
                        if latest_datetime_obj is None or current_file_datetime_obj > latest_datetime_obj:
                            latest_datetime_obj = current_file_datetime_obj
                            latest_file_path = os.path.join(directory_path, filename)
        except Exception as e:
            self._auto_display_status_message(f"Err scanning CSV dir: {e}", True, 5000)
            return None

        if not latest_file_path:
            self._auto_display_status_message(f"No CSVs for ch {channel_str} in dir", True, 10000)
            return None

        try:
            with open(latest_file_path, 'r', encoding='utf-8', newline='') as f:
                reader = csv.reader(f)
                header = next(reader, None)
                if not header: return None
                col_idx = header.index(column_name)
                last_row_data = None
                for row in reader:
                    if any(field.strip() for field in row):
                        last_row_data = row
                if not last_row_data: return None
                return float(last_row_data[col_idx])
        except (ValueError, IndexError):
            self._auto_display_status_message(f"Err: Column '{column_name}' missing/invalid in {os.path.basename(latest_file_path)}", True, 10000)
            return None
        except Exception as e:
            self._auto_display_status_message(f"Err reading CSV {os.path.basename(latest_file_path)}: {e}", True, 5000)
            return None
           
    def _calculate_soc_from_nernst(self, ocv, temp_k):
        if temp_k <= 0: return 0.0
        try:
            exponent = (-FARADAY_CONSTANT / (2 * GAS_CONSTANT_R * temp_k)) * (ocv - 1.4)
            soc = 1 / (1 + np.exp(exponent))
            return soc
        except (ValueError, OverflowError):
            return 0.0

    def _calculate_flow_ul_min(self, current_A, lambda_val, n_cell_val, soc_val, is_charging_flag):
        safe_soc = max(0.00001, min(0.99999, soc_val)) 
        soc_term_in_formula = (1.0 - safe_soc) if is_charging_flag else safe_soc
        try:
            if abs(current_A) < 1e-9: return 0
            denominator = FARADAY_CONSTANT * soc_term_in_formula * ELECTROLYTE_CONCENTRATION_MOL_PER_UL
            if abs(denominator) < 1e-12: self._auto_display_status_message("Err: Calc denominator near zero.", True, 5000); return 0 
            return lambda_val * (abs(current_A) * n_cell_val) / denominator * 60.0
        except Exception as e: self._auto_display_status_message(f"Err in flow calc: {e}", True, 5000); return 0

    def _update_auto_control_ui_state(self):
        is_active = self.auto_flow_control_active
        self.auto_toggle_control_button.setText("Stop Auto Control" if is_active else "Start Auto Control")
        self._set_auto_control_inputs_enabled(not is_active)
        if is_active:
            self.auto_control_status_label.setText("Status: Active.")
            self.auto_control_status_label.setStyleSheet("color: blue; font-style: italic;")
        else:
            self.auto_control_status_label.setText("Status: Inactive.")
            self.auto_control_status_label.setStyleSheet("font-style: italic;")
            self.auto_current_soc_display_label.setText("N/A")
            self.avg_temp_display_label.setText("Avg Temp: N/A")

    def _toggle_auto_control(self):
        if not self.auto_flow_control_active:
            pump_a_is_ready = hasattr(self, 'pump_a_widget') and self.pump_a_widget.connected
            pump_b_is_ready = hasattr(self, 'pump_b_widget') and self.pump_b_widget.connected
            if not (pump_a_is_ready and pump_b_is_ready):
                QMessageBox.warning(self, "Connection Error", "Both pumps must be connected to start.")
                return

            try:
                interval_ms = int(self.auto_update_interval_edit.text()) * 1000
                if interval_ms <= 500: raise ValueError("Interval too short.")
                float(self.auto_lambda_c_edit.text()); float(self.auto_lambda_d_edit.text())
                int(self.auto_n_cell_edit.text())
                if not os.path.isdir(self.auto_csv_dir_edit.text()): 
                    QMessageBox.critical(self, "Input Error", f"CSV dir not found:\n{self.auto_csv_dir_edit.text()}"); return
            except (ValueError, FileNotFoundError): 
                QMessageBox.critical(self, "Input Error", "Invalid Auto Control parameters."); return
            
            self.auto_flow_control_active = True
            self.auto_flow_timer.start(interval_ms)
            self._auto_update_flow_rate()
        
        else: 
            self.auto_flow_timer.stop()
            self.auto_flow_control_active = False

        self._update_auto_control_ui_state()

    def _set_auto_control_inputs_enabled(self, enabled_bool):
        widgets_to_toggle = [
            self.auto_csv_dir_edit, self.auto_browse_csv_dir_button,
            self.auto_channel_no_combo, self.auto_soc_channel_combo,
            self.auto_min_flow_edit, self.auto_max_flow_edit,
            self.auto_lambda_c_edit, self.auto_lambda_d_edit,
            self.auto_n_cell_edit, self.auto_update_interval_edit,
            self.temp_sensor_1_combo, self.temp_sensor_2_combo
        ]
        for widget in widgets_to_toggle:
            widget.setEnabled(enabled_bool)

    def closeEvent(self, event):
        if self.is_master_logging_active: self.handle_master_toggle_logging() 
        if self.auto_flow_control_active: self.auto_flow_timer.stop() 
        if hasattr(self, 'pump_a_widget'): self.pump_a_widget.close() 
        if hasattr(self, 'pump_b_widget'): self.pump_b_widget.close() 
        if self.power_meter_instance and self.is_power_meter_connected: self.power_meter_instance.disconnect() 
        if self.arduino_instance and self.is_arduino_connected: self.arduino_instance.disconnect()
        self.power_meter_update_timer.stop()
        self.arduino_update_timer.stop()
        print("Main window closing...")
        super().closeEvent(event)

if __name__ == '__main__':
    app = QApplication(sys.argv)
    main_win = MainWindow()
    main_win.show()
    sys.exit(app.exec())
