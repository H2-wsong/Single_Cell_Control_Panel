# Control_Panel.py

import sys
import os
import re
import numpy as np
import csv
from datetime import datetime

from PyQt6.QtWidgets import QApplication, QMainWindow, QMessageBox, QFileDialog
from PyQt6.QtCore import QTimer, Qt
from PyQt6.QtGui import QIcon, QPixmap

try:
    from Src.gui import MainWindowUI
    from Src.Pump_Control import SimdosPump
    from Src.PowerMeter_Control import GPM8213PowerMeter
    from Src.Arduino import ArduinoControl
except ImportError as e:
    print(f"필수 모듈 임포트 실패: {e}\nSrc 폴더와 그 안의 파일들이 올바르게 위치해 있는지 확인하세요.")
    sys.exit()

# --- 기본 상수 및 경로 설정 ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_LOG_PATH = os.path.join(BASE_DIR, "log")
if not os.path.exists(DEFAULT_LOG_PATH):
    os.makedirs(DEFAULT_LOG_PATH)
DEFAULT_PUMP_CONFIGS = {
    "Pump_A": {"port": "COM3", "address": "00", "model": "SIMDOS10", "flow_rate": "30000"},
    "Pump_B": {"port": "COM4", "address": "00", "model": "SIMDOS10", "flow_rate": "30000"}
}
DEFAULT_POWER_METER_PORT = 'COM5'
DEFAULT_AUTO_CSV_DIR = r"C:\Users\ECHEM\Desktop\Oscar\Backup"
DEFAULT_ARDUINO_PORT = 'COM8'
FARADAY_CONSTANT, GAS_CONSTANT_R = 96485.3, 8.314472
ELECTROLYTE_CONCENTRATION_MOLAR = 1.7
ELECTROLYTE_CONCENTRATION_MOL_PER_UL = ELECTROLYTE_CONCENTRATION_MOLAR * 1E-6

class MainWindow(QMainWindow):
    """메인 컨트롤러 클래스. UI와 장비 제어 로직을 연결합니다."""
    # UI 클래스에서 사용할 상수들을 클래스 변수로 정의
    DEFAULT_PUMP_CONFIGS = DEFAULT_PUMP_CONFIGS
    DEFAULT_LOG_PATH = DEFAULT_LOG_PATH
    DEFAULT_AUTO_CSV_DIR = DEFAULT_AUTO_CSV_DIR
    DEFAULT_POWER_METER_PORT = DEFAULT_POWER_METER_PORT
    DEFAULT_ARDUINO_PORT = DEFAULT_ARDUINO_PORT

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Pump & Power Meter Controller")
        icon_path = os.path.join(BASE_DIR, "Src", "logo.ico")
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))

        self._init_variables()
        
        ui = MainWindowUI()
        ui.setupUi(self)
        self._connect_signals()
        
        self._load_logo()
        self._update_master_pump_buttons_state()
        self._update_master_logging_ui()
        
        self._start_status_timer()
        self.clock_timer.start(1000)

    def _init_variables(self):
        """애플리케이션의 상태 변수들을 초기화합니다."""
        self.power_meter_instance, self.arduino_instance = None, None
        self.is_power_meter_connected, self.is_arduino_connected = False, False
        self.is_logging_active, self.auto_flow_control_active = False, False
        self.log_file, self.log_writer = None, None
        self.arduino_relay_state = "UNKNOWN"
        self.log_path = self.DEFAULT_LOG_PATH
        
        # 타이머 인스턴스 생성
        self.status_update_timer, self.logging_timer, self.auto_flow_timer = QTimer(self), QTimer(self), QTimer(self)
        self.power_meter_update_timer, self.arduino_update_timer = QTimer(self), QTimer(self)
        self.valve_close_timer, self.clock_timer = QTimer(self), QTimer(self)
        self.valve_close_timer.setSingleShot(True)
        
        self.power_meter_update_interval, self.arduino_update_interval = 500, 2000
        self.valve_last_triggered_cycle = -1

    def _connect_signals(self):
        """UI 위젯의 시그널을 핸들러 메소드에 연결합니다."""
        self.status_update_timer.timeout.connect(self._update_main_status_display)
        self.status_interval_set_button.clicked.connect(self._on_status_interval_changed)
        self.logging_timer.timeout.connect(self.log_unified_data_row)
        self.auto_flow_timer.timeout.connect(self._auto_update_flow_rate)
        self.power_meter_update_timer.timeout.connect(self.update_power_meter_status)
        self.arduino_update_timer.timeout.connect(self.update_arduino_status)
        self.valve_close_timer.timeout.connect(self.handle_close_relay)
        self.clock_timer.timeout.connect(self._update_clock)
        self.set_log_path_button.clicked.connect(self._handle_set_log_path)
        self.master_toggle_logging_button.clicked.connect(self.handle_toggle_logging)
        self.master_connect_all_button.clicked.connect(self.handle_master_connect_all)
        self.master_start_all_button.clicked.connect(self.handle_master_start_all)
        self.master_stop_all_button.clicked.connect(self.handle_master_stop_all)
        self.auto_browse_csv_dir_button.clicked.connect(self._auto_browse_csv_dir)
        self.auto_toggle_control_button.clicked.connect(self._toggle_auto_control)
        self.arduino_connect_button.clicked.connect(self.handle_connect_arduino)
        self.relay_open_button.clicked.connect(self.handle_open_relay)
        self.relay_close_button.clicked.connect(self.handle_close_relay)
        self.pm_connect_button.clicked.connect(self.handle_connect_power_meter)
        self.pump_a_widget.connection_status_changed.connect(self._update_master_pump_buttons_state)
        self.pump_b_widget.connection_status_changed.connect(self._update_master_pump_buttons_state)
    
    # --- UI 업데이트 및 상태 관리 ---
    def _load_logo(self):
        logo_path = os.path.join(BASE_DIR, "Src", "logo.ico")
        if os.path.exists(logo_path):
            pixmap = QPixmap(logo_path)
            self.logo_label.setPixmap(pixmap.scaled(96, 96, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))

    def _update_clock(self):
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.clock_label.setText(current_time)

    def _start_status_timer(self):
        """알림 없이 상태 업데이트 타이머를 시작/재시작합니다."""
        self.status_update_timer.stop()
        try:
            interval_ms = int(self.status_interval_edit.text()) * 1000
            if interval_ms > 0: self.status_update_timer.start(interval_ms)
        except (ValueError, TypeError): pass

    def _on_status_interval_changed(self):
        """'Set' 버튼을 눌렀을 때 알림과 함께 타이머를 재시작합니다."""
        self._start_status_timer()
        if self.status_update_timer.isActive():
            interval_sec = self.status_update_timer.interval() / 1000
            QMessageBox.information(self, "Status Update", f"Status update interval set to {interval_sec} seconds.")
        else:
            QMessageBox.warning(self, "Input Error", "Please enter a valid number for the interval.")

    def _update_main_status_display(self):
        """최상단 상태 패널을 주기적으로 업데이트하고, 릴레이 자동 제어 조건을 확인합니다."""
        dir_path, channel_str = self.auto_csv_dir_edit.text(), self.auto_channel_no_combo.currentText()
        latest_file = self._find_latest_csv_file(dir_path, channel_str)
        if not latest_file:
            self.status_channel_label.setText("Channel : File not found")
            self.status_cycle_label.setText("Cycle : N/A")
            self.status_step_label.setText("Step : N/A")
            return
        try:
            with open(latest_file, 'r', encoding='utf-8', errors='ignore') as f:
                reader = csv.reader(f); header = next(reader, None)
                if not header: return
                col_indices = {"ch": header.index("Channel Index"), "cycle": header.index("Cycle Number"), "step": header.index("Step Type")}
                last_row = None
                for row in reader:
                    if len(row) > max(col_indices.values()): last_row = row
                if last_row:
                    ch_val, cycle_val, step_val = last_row[col_indices['ch']], last_row[col_indices['cycle']], last_row[col_indices['step']]
                    self.status_channel_label.setText(f"Channel : {ch_val}")
                    self.status_cycle_label.setText(f"Cycle Number : {cycle_val}")
                    self.status_step_label.setText(f"Step : {step_val}")
                    # 상태 정보를 읽은 후, 릴레이 자동 제어 로직을 호출합니다.
                    self._check_and_trigger_valve(cycle_val, step_val)
        except (ValueError, IndexError, FileNotFoundError):
            self.status_channel_label.setText("Channel : Error")
            self.status_cycle_label.setText("Cycle Number : Error")
            self.status_step_label.setText("Step : Parse Error")
            
    # --- 자동 제어 로직 (릴레이 및 유량) ---
    def _check_and_trigger_valve(self, current_cycle_str, current_step_str):
        """현재 사이클과 스텝을 확인하여 릴레이(밸브) 작동 조건을 검사하고 실행합니다."""
        if not self.is_arduino_connected: return
        try:
            base_cycle, interval = int(self.valve_base_cycle_edit.text()), int(self.valve_interval_edit.text())
            duration_min, current_cycle = float(self.valve_duration_edit.text()), int(current_cycle_str)
            
            # 조건 검사
            is_charge_step = "charge" in current_step_str.lower()
            is_target_cycle = (current_cycle >= base_cycle) and ((current_cycle - base_cycle) % interval == 0)
            is_new_cycle = (current_cycle != self.valve_last_triggered_cycle)

            if is_charge_step and is_target_cycle and is_new_cycle:
                self.handle_open_relay() # 기존 릴레이 열기 함수 호출
                self.valve_last_triggered_cycle = current_cycle
                self.valve_close_timer.start(int(duration_min * 60 * 1000))
                self._arduino_display_message(f"Cycle {current_cycle}: Auto-opening relay for {duration_min} min.")
        except (ValueError, TypeError):
            # UI에 입력된 값이 숫자가 아니면 조용히 무시
            pass

    def _auto_update_flow_rate(self):
        """CSV파일의 최신 데이터를 기반으로 펌프의 유량을 자동으로 계산하고 설정합니다."""
        csv_dir, current_channel_str = self.auto_csv_dir_edit.text(), self.auto_channel_no_combo.currentText()
        current_mA, voltage_V_ocv = self._get_latest_value_from_csv(csv_dir, current_channel_str, "Current(mA)"), self._get_latest_avg_aux_voltage_from_csv(csv_dir, current_channel_str)
        if current_mA is None or voltage_V_ocv is None:
            self._auto_display_status_message("Could not read Current or Voltage from CSV.", True, 5000); return
        try:
            # UI에서 제어 파라미터 읽기
            temp_indices = [self.temp_sensor_1_combo.currentIndex(), self.temp_sensor_2_combo.currentIndex()]
            temps = [self.arduino_instance.get_temperature(i) if self.is_arduino_connected else None for i in temp_indices]
            for i, temp_val in zip(temp_indices, temps):
                self.temp_display_labels[i].setText(f"A{i}: {temp_val:.2f}" if temp_val is not None else f"A{i}: Error")
            valid_temps, avg_temp_c = [t for t in temps if t is not None], sum(valid_temps) / len(valid_temps) if valid_temps else 25.0
            self.avg_temp_display_label.setText(f"Avg Temp: {avg_temp_c:.2f} °C" if valid_temps else "Avg Temp: N/A (Default 25°C)")
            temp_k = avg_temp_c + 273.15
            
            lambda_c, lambda_d = float(self.auto_lambda_c_edit.text()), float(self.auto_lambda_d_edit.text())
            n_cell, user_min_flow, user_max_flow = int(self.auto_n_cell_edit.text()), int(self.auto_min_flow_edit.text()), int(self.auto_max_flow_edit.text())
        except (ValueError, TypeError) as e:
            self._auto_display_status_message(f"Error: Invalid auto-control parameters. {e}", True, 5000); return
        
        # 유량 계산 및 펌프에 설정
        current_A, real_soc = current_mA / 1000.0, self._calculate_soc_from_nernst(voltage_V_ocv, temp_k)
        selected_lambda = lambda_c if current_A >= 0 else lambda_d
        calculated_flow = self._calculate_flow_ul_min(current_A, selected_lambda, n_cell, real_soc, current_A >= 0)
        flow_to_set = int(round(max(user_min_flow, min(calculated_flow, user_max_flow))))
        
        for pump_widget in [self.pump_a_widget, self.pump_b_widget]:
            if pump_widget.connected:
                pump_widget.pump_instance.set_mode(0)
                pump_widget.pump_instance.set_flow_rate_run_mode(flow_to_set)
                pump_widget.pump_instance.start_pump()
                pump_widget.update_pump_status()
        self._auto_display_status_message(f"I:{current_A:.3f}A, V_avg:{voltage_V_ocv:.3f}V -> SOC:{real_soc:.3f} -> Set Flow:{flow_to_set}µl/min", False, 10000)
    
    # --- 파일 처리 및 계산 헬퍼 함수 ---
    def _get_latest_value_from_csv(self, directory_path, channel_str, column_name):
        latest_file_path = self._find_latest_csv_file(directory_path, channel_str)
        if not latest_file_path: return None
        try:
            with open(latest_file_path, 'r', encoding='utf-8', errors='ignore') as f:
                reader = csv.reader(f); header = next(reader, None)
                if not header: return None
                col_idx = header.index(column_name); last_row_data = None
                for row in reader:
                    if len(row) > col_idx and row[col_idx]: last_row_data = row
                if not last_row_data: return None
                return float(last_row_data[col_idx])
        except (ValueError, IndexError, FileNotFoundError) as e:
            self._auto_display_status_message(f"Error reading {column_name}: {e}", True, 10000)
            return None

    def _get_latest_avg_aux_voltage_from_csv(self, directory_path, channel_str):
        column_name, latest_file_path = "auxiliary voltage(V)", self._find_latest_csv_file(directory_path, channel_str)
        if not latest_file_path: return None
        try:
            with open(latest_file_path, 'r', encoding='utf-8', errors='ignore') as f:
                reader = csv.reader(f); header = next(reader, None)
                if not header: return None
                col_idx = header.index(column_name); last_row_data = None
                for row in reader:
                    if len(row) > col_idx and row[col_idx]: last_row_data = row
                if not last_row_data: return None
                raw_str, parts = last_row_data[col_idx], raw_str.split(':')
                if len(parts) < 2: return None
                val1_str, val2_str = parts[0].split(';')[-1].replace(']', ''), parts[1].split(';')[-1].replace(']', '')
                return (float(val1_str) + float(val2_str)) / 2.0
        except (ValueError, IndexError, FileNotFoundError) as e:
            self._auto_display_status_message(f"Error parsing {column_name}: {e}", True, 10000)
            return None

    def _find_latest_csv_file(self, directory_path, channel_str):
        if not os.path.isdir(directory_path): return None
        file_prefix, latest_file_path, latest_datetime_obj = f"Data-24-{channel_str} ", None, None
        datetime_pattern = re.compile(r"(\d{4}-\d{2}-\d{2} \d{2}-\d{2}-\d{2})")
        try:
            for filename in os.listdir(directory_path):
                if filename.startswith(file_prefix) and filename.endswith(".csv"):
                    match = datetime_pattern.search(filename)
                    if match:
                        current_dt = datetime.strptime(match.group(1), "%Y-%m-%d %H-%M-%S")
                        if latest_datetime_obj is None or current_dt > latest_datetime_obj:
                            latest_datetime_obj, latest_file_path = current_dt, os.path.join(directory_path, filename)
            return latest_file_path
        except Exception: return None

    def _calculate_soc_from_nernst(self, ocv, temp_k):
        if temp_k <= 0: return 0.0
        try:
            exponent = (-FARADAY_CONSTANT / (2 * GAS_CONSTANT_R * temp_k)) * (ocv - 1.4)
            with np.errstate(over='ignore'): soc = 1 / (1 + np.exp(exponent))
            return soc if not np.isnan(soc) else 0.0
        except (ValueError, OverflowError): return 0.0

    def _calculate_flow_ul_min(self, current_A, lambda_val, n_cell_val, soc_val, is_charging):
        safe_soc, soc_term = max(1e-5, min(1.0 - 1e-5, soc_val)), (1.0 - safe_soc) if is_charging else safe_soc
        try:
            if abs(current_A) < 1e-9 or abs(soc_term) < 1e-9: return 0
            return lambda_val * (abs(current_A) * n_cell_val) / (FARADAY_CONSTANT * soc_term * ELECTROLYTE_CONCENTRATION_MOL_PER_UL) * 60.0
        except Exception: return 0

    # ... (이하 모든 핸들러 및 나머지 메소드는 이전 답변과 동일) ...
    def _handle_set_log_path(self):
        directory = QFileDialog.getExistingDirectory(self, "Select Log Directory", self.log_path)
        if directory:
            self.log_path = directory
            self.set_log_path_button.setToolTip(f"Current Log Path:\n{self.log_path}")
            QMessageBox.information(self, "Log Path Set", f"Log directory has been set to:\n{self.log_path}")

    def handle_toggle_logging(self):
        if not self.is_logging_active:
            if not self.log_path or not os.path.isdir(self.log_path):
                QMessageBox.warning(self, "Path Error", "A valid log directory must be set first."); return
            try:
                interval_sec = int(self.log_interval_edit.text())
                if interval_sec <= 0: raise ValueError("Interval must be positive")
            except (ValueError, TypeError):
                QMessageBox.warning(self, "Input Error", "Log interval must be a positive integer."); return
            try:
                time_str = datetime.now().strftime("%Y%m%d_%H%M%S")
                filepath = os.path.join(self.log_path, f"Log_{time_str}.csv")
                self.log_file = open(filepath, 'w', newline='', encoding='utf-8')
                self.log_writer = csv.writer(self.log_file)
                self.log_writer.writerow(['Timestamp', 'PumpA_FlowRate_ul_min', 'PumpA_Mode', 'PumpB_FlowRate_ul_min', 'PumpB_Mode', 'PM_Voltage_V', 'PM_Current_A', 'PM_Power_W', 'PM_Energy_Wh', 'Arduino_Relay_State', 'Temp_A0_C', 'Temp_A1_C', 'Temp_A2_C', 'Temp_A3_C', 'Temp_A4_C'])
                if self.is_power_meter_connected: self.power_meter_instance.start_energy_accumulation()
                self.logging_timer.start(interval_sec * 1000)
                self.is_logging_active = True
                QMessageBox.information(self, "Logging Control", f"Logging started to:\n{filepath}")
            except Exception as e:
                QMessageBox.critical(self, "Logging Error", f"Failed to start logging: {e}")
                if self.log_file: self.log_file.close()
                self.is_logging_active = False
        else:
            self.logging_timer.stop()
            if self.log_file: self.log_file.close()
            if self.is_power_meter_connected: self.power_meter_instance.stop_energy_accumulation()
            self.is_logging_active = False
            self.log_file, self.log_writer = None, None
            QMessageBox.information(self, "Logging Control", "Logging stopped.")
        self._update_master_logging_ui()

    def log_unified_data_row(self):
        if not self.is_logging_active or self.log_writer is None: return
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        pa_widget, pb_widget = self.pump_a_widget, self.pump_b_widget
        pump_a_rate, pump_a_mode = (pa_widget.pump_instance.get_flow_rate_run_mode(), pa_widget.pump_instance.get_mode()) if pa_widget.connected else ("N/A", "N/A")
        pump_b_rate, pump_b_mode = (pb_widget.pump_instance.get_flow_rate_run_mode(), pb_widget.pump_instance.get_mode()) if pb_widget.connected else ("N/A", "N/A")
        pm_v, pm_i, pm_p, pm_wh = "N/A", "N/A", "N/A", "N/A"
        if self.is_power_meter_connected:
            readings = self.power_meter_instance.get_readings()
            if readings: pm_v, pm_i, pm_p, pm_wh = readings.get('voltage', 'Err'), readings.get('current', 'Err'), readings.get('power', 'Err'), readings.get('energy_wh', 'Err')
            else: pm_v, pm_i, pm_p, pm_wh = "Err", "Err", "Err", "Err"
        relay_state, temps = "N/A", ["N/A"] * 5
        if self.is_arduino_connected:
            relay_state = self.arduino_relay_state
            for i in range(5):
                temp = self.arduino_instance.get_temperature(i)
                temps[i] = f"{temp:.2f}" if temp is not None else "Error"
        data_row = [timestamp, pump_a_rate, pump_a_mode, pump_b_rate, pump_b_mode, pm_v, pm_i, pm_p, pm_wh, relay_state] + temps
        self.log_writer.writerow(data_row)
        
    def _update_master_logging_ui(self):
        self.master_toggle_logging_button.setText("Record OFF" if self.is_logging_active else "Record ON")
        widgets_to_toggle = [self.set_log_path_button, self.log_interval_edit]
        for widget in widgets_to_toggle: widget.setEnabled(not self.is_logging_active)
        self.pm_logging_status_label.setText(f"Logging: {'Active' if self.is_logging_active and self.is_power_meter_connected else 'Inactive'}")
        self.set_log_path_button.setToolTip(f"Current Log Path:\n{self.log_path}")

    def _auto_browse_csv_dir(self):
        directory = QFileDialog.getExistingDirectory(self, "Select CSV Data Directory", self.auto_csv_dir_edit.text())
        if directory: self.auto_csv_dir_edit.setText(directory)

    def _auto_display_status_message(self, message, is_error=False, duration=0):
        prefix = "Status: Active. " if self.auto_flow_control_active else "Status: Inactive. "
        self.auto_control_status_label.setText(prefix + message)
        self.auto_control_status_label.setStyleSheet(f"color: {'red' if is_error else 'blue'}; font-style: italic;")
        if duration > 0: QTimer.singleShot(duration, lambda: (self.auto_control_status_label.setText("Status: Active." if self.auto_flow_control_active else "Status: Inactive."), self.auto_control_status_label.setStyleSheet("font-style: italic;")))

    def _pm_display_message(self, message, is_error=False, duration=0):
        self.pm_message_label.setText(message); self.pm_message_label.setStyleSheet(f"color: {'red' if is_error else 'black'};")
        if duration > 0: QTimer.singleShot(duration, lambda: self.pm_message_label.setText(""))

    def _arduino_display_message(self, message, is_error=False, duration=0):
        self.arduino_message_label.setText(message); self.arduino_message_label.setStyleSheet(f"color: {'red' if is_error else 'blue'};")
        if duration > 0: QTimer.singleShot(duration, lambda: self.arduino_message_label.setText(""))
    
    def handle_master_connect_all(self):
        all_connected = self.pump_a_widget.connected and self.pump_b_widget.connected
        if all_connected:
            if self.pump_a_widget.connected: self.pump_a_widget.handle_connect_pump()
            if self.pump_b_widget.connected: self.pump_b_widget.handle_connect_pump()
        else:
            if not self.pump_a_widget.connected: self.pump_a_widget.handle_connect_pump()
            if not self.pump_b_widget.connected: self.pump_b_widget.handle_connect_pump()

    def handle_master_start_all(self):
        if self.pump_a_widget.connected: self.pump_a_widget.handle_start_pump()
        if self.pump_b_widget.connected: self.pump_b_widget.handle_start_pump()

    def handle_master_stop_all(self): 
        if self.auto_flow_control_active: self._toggle_auto_control()
        if self.pump_a_widget.connected: self.pump_a_widget.handle_stop_pump()
        if self.pump_b_widget.connected: self.pump_b_widget.handle_stop_pump()

    def _update_master_pump_buttons_state(self):
        any_pump_connected = self.pump_a_widget.connected or self.pump_b_widget.connected
        all_pumps_connected = self.pump_a_widget.connected and self.pump_b_widget.connected
        self.master_start_all_button.setEnabled(any_pump_connected)
        self.master_stop_all_button.setEnabled(any_pump_connected)
        self.master_connect_all_button.setText("🔌 Disconnect All" if all_pumps_connected else "🔗 Connect All")
    
    def _toggle_auto_control(self):
        if not self.auto_flow_control_active:
            if not (self.pump_a_widget.connected and self.pump_b_widget.connected):
                QMessageBox.warning(self, "Connection Error", "Both pumps must be connected to start auto-control."); return
            try:
                interval_ms = int(self.auto_update_interval_edit.text()) * 1000
                if interval_ms <= 500: raise ValueError("Interval too short.")
                if not os.path.isdir(self.auto_csv_dir_edit.text()):
                    QMessageBox.critical(self, "Input Error", f"CSV directory not found:\n{self.auto_csv_dir_edit.text()}"); return
            except (ValueError, FileNotFoundError):
                QMessageBox.critical(self, "Input Error", "Invalid auto-control parameters."); return
            self.auto_flow_control_active = True
            self.auto_flow_timer.start(interval_ms)
            self._auto_update_flow_rate()
        else:
            self.auto_flow_timer.stop()
            self.auto_flow_control_active = False
        self._update_auto_control_ui_state()

    def _update_auto_control_ui_state(self):
        is_active = self.auto_flow_control_active
        self.auto_toggle_control_button.setText("Stop Auto Control" if is_active else "Start Auto Control")
        widgets_to_toggle = [self.auto_channel_no_combo, self.auto_min_flow_edit, self.auto_max_flow_edit, self.auto_lambda_c_edit, self.auto_lambda_d_edit, self.auto_n_cell_edit, self.auto_update_interval_edit, self.temp_sensor_1_combo, self.temp_sensor_2_combo]
        for widget in widgets_to_toggle: widget.setEnabled(not is_active)
        self._auto_display_status_message("Control " + ("activated." if is_active else "deactivated."))

    def handle_connect_arduino(self):
        if not self.is_arduino_connected:
            port = self.arduino_port_edit.text()
            if not port: self._arduino_display_message("Arduino COM Port must be entered.", True, 3000); return
            self.arduino_instance = ArduinoControl(port=port)
            self._arduino_display_message(f"Connecting to Arduino on {port}...", False)
            QApplication.processEvents()
            if self.arduino_instance.connect():
                self.is_arduino_connected = True
                self.arduino_status_label.setText("Status: Connected"); self.arduino_status_label.setStyleSheet("font-weight: bold; color: green;")
                self.arduino_port_edit.setEnabled(False); self.arduino_connect_button.setText("Disconnect")
                self.relay_open_button.setEnabled(True); self.relay_close_button.setEnabled(True)
                self.arduino_update_timer.start(self.arduino_update_interval)
                self.handle_close_relay()
            else:
                self._arduino_display_message(f"Failed to connect to Arduino on {port}.", True, 5000); self.arduino_instance = None
        else:
            self.arduino_update_timer.stop()
            if self.is_arduino_connected: self.handle_close_relay()
            if self.arduino_instance: self.arduino_instance.disconnect()
            self.is_arduino_connected = False; self.arduino_instance = None
            self.arduino_status_label.setText("Status: Disconnected"); self.arduino_status_label.setStyleSheet("font-weight: bold; color: red;")
            self.arduino_port_edit.setEnabled(True); self.arduino_connect_button.setText("Connect")
            self.relay_open_button.setEnabled(False); self.relay_close_button.setEnabled(False)
            self.arduino_relay_state = "UNKNOWN"
            for label in self.temp_display_labels: label.setText(label.text().split(':')[0] + ": N/A")

    def handle_open_relay(self):
        if self.is_arduino_connected:
            self.arduino_instance.open_relay()
            self.arduino_relay_state = "OPEN"
            self._arduino_display_message("밸브 열림", False, 3000)

    def handle_close_relay(self):
        if self.is_arduino_connected:
            self.arduino_instance.close_relay()
            self.arduino_relay_state = "CLOSE"
            self._arduino_display_message("밸브 닫힘", False, 3000)

    def update_arduino_status(self):
        if self.is_arduino_connected:
            for i in range(5):
                temp = self.arduino_instance.get_temperature(i)
                self.temp_display_labels[i].setText(f"A{i}: {temp:.2f}" if temp is not None else f"A{i}: Error")

    def handle_connect_power_meter(self):
        if not self.is_power_meter_connected:
            port = self.pm_port_edit.text()
            if not port: self._pm_display_message("Power Meter COM Port must be entered.", True, 5000); return
            self.power_meter_instance = GPM8213PowerMeter(port=port)
            if self.power_meter_instance.connect() and self.power_meter_instance.setup_meter():
                self.is_power_meter_connected = True
                self.pm_status_label.setText("Status: Connected"); self.pm_status_label.setStyleSheet("font-weight: bold; color: green;")
                self.pm_port_edit.setEnabled(False); self.pm_connect_button.setText("Disconnect")
                self.power_meter_update_timer.start(self.power_meter_update_interval)
            else:
                self._pm_display_message(f"Failed to connect to Power Meter on {port}.", True, 5000)
                if self.power_meter_instance: self.power_meter_instance.disconnect()
                self.power_meter_instance = None
        else:
            self.power_meter_update_timer.stop()
            if self.power_meter_instance: self.power_meter_instance.disconnect()
            self.is_power_meter_connected = False; self.power_meter_instance = None
            self.pm_status_label.setText("Status: Disconnected"); self.pm_status_label.setStyleSheet("font-weight: bold; color: red;")
            self.pm_port_edit.setEnabled(True); self.pm_connect_button.setText("Connect")
            self.pm_current_power_label.setText("N/A"); self.pm_accumulated_energy_label.setText("N/A")
        self._update_master_logging_ui()

    def update_power_meter_status(self):
        if self.is_power_meter_connected:
            readings = self.power_meter_instance.get_readings()
            if readings:
                self.pm_current_power_label.setText(f"{readings['power']:.4f} W")
                self.pm_accumulated_energy_label.setText(f"{readings['energy_wh']:.4f} Wh")
            else:
                self.pm_current_power_label.setText("Read Error")
        
    def closeEvent(self, event):
        if self.is_logging_active: self.handle_toggle_logging()
        if self.auto_flow_control_active: self.auto_flow_timer.stop()
        
        self.pump_a_widget.close()
        self.pump_b_widget.close()
        
        if self.is_power_meter_connected: self.power_meter_instance.disconnect()
        if self.is_arduino_connected:
            self.handle_close_relay()
            self.arduino_instance.disconnect()
        
        self.status_update_timer.stop(); self.logging_timer.stop(); self.clock_timer.stop()
        self.power_meter_update_timer.stop(); self.arduino_update_timer.stop()
        
        print("Main window closing...")
        super().closeEvent(event)


if __name__ == '__main__':
    app = QApplication(sys.argv)
    main_win = MainWindow()
    main_win.show()
    sys.exit(app.exec())