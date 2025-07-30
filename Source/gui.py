# Src/gui.py

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QLineEdit,
    QPushButton, QGroupBox, QComboBox, QFormLayout, QApplication, QCheckBox
)
from PyQt6.QtGui import QPalette, QColor, QFont
from PyQt6.QtCore import QTimer, pyqtSignal, Qt

class PumpControlWidget(QWidget):
    # 각 펌프 제어를 위한 독립적인 UI 위젯 클래스
    connection_status_changed = pyqtSignal(bool)

    def __init__(self, pump_name, default_config):
        super().__init__()
        self.pump_name = pump_name
        self.default_config = default_config
        self.pump_instance = None
        self.connected = False
        self.current_mode_str = "N/A"
        
        # UI 업데이트를 위한 타이머 설정
        self.update_timer = QTimer(self)
        self.update_timer.timeout.connect(self.update_pump_status)
        self.update_timer_interval = 500
        
        self.init_ui()
        self._connect_handlers()

    def init_ui(self):
        # UI 요소 생성 및 레이아웃 배치
        main_layout = QVBoxLayout(self)
        group_box = QGroupBox(self.pump_name)
        main_layout.addWidget(group_box)
        layout = QGridLayout(group_box)
        
        layout.addWidget(QLabel("COM Port:"), 0, 0)
        self.port_edit = QLineEdit(self.default_config.get("port", ""))
        layout.addWidget(self.port_edit, 0, 1)
        self.connect_button = QPushButton("Connect")
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
        layout.addWidget(self.start_button, 3, 0)
        self.stop_button = QPushButton("Stop Pump")
        layout.addWidget(self.stop_button, 3, 1)
        self.set_run_mode_button = QPushButton("Set to Run Mode")
        layout.addWidget(self.set_run_mode_button, 3, 2)
        self.prime_button = QPushButton("Prime (1 stroke)")
        layout.addWidget(self.prime_button, 3, 3)
        
        layout.addWidget(QLabel("Set Flow Rate (µl/min):"), 4, 0)
        self.flow_rate_set_edit = QLineEdit(self.default_config.get("flow_rate", "30000"))
        layout.addWidget(self.flow_rate_set_edit, 4, 1)
        self.set_flow_rate_button = QPushButton("Set Flow Rate")
        layout.addWidget(self.set_flow_rate_button, 4, 2, 1, 2)
        
        layout.addWidget(QLabel("Current Set Rate:"), 5, 0)
        self.current_flow_rate_label = QLabel("N/A µl/min")
        layout.addWidget(self.current_flow_rate_label, 5, 1, 1, 3)
        
        self.message_label = QLabel("")
        self.message_label.setWordWrap(True)
        layout.addWidget(self.message_label, 6, 0, 1, 4)
        
        self._update_ui_for_connection_state()

    def _connect_handlers(self):
        # 위젯 내부의 시그널-슬롯 연결
        self.connect_button.clicked.connect(self.handle_connect_pump)
        self.start_button.clicked.connect(self.handle_start_pump)
        self.stop_button.clicked.connect(self.handle_stop_pump)
        self.set_run_mode_button.clicked.connect(self.handle_set_run_mode)
        self.prime_button.clicked.connect(self.handle_prime_pump)
        self.set_flow_rate_button.clicked.connect(self.handle_set_flow_rate)

    def _set_status_color(self, connected_bool):
        palette = self.status_label.palette()
        color = QColor("green") if connected_bool else QColor("red")
        palette.setColor(QPalette.ColorRole.WindowText, color)
        self.status_label.setPalette(palette)

    def _update_ui_for_connection_state(self):
        # 연결 상태에 따라 UI 활성화/비활성화 및 텍스트 변경
        is_connected = self.connected
        self.port_edit.setEnabled(not is_connected)
        self.connect_button.setText("Disconnect" if is_connected else "Connect")
        for widget in [self.start_button, self.stop_button, self.set_run_mode_button,
                       self.prime_button, self.flow_rate_set_edit, self.set_flow_rate_button]:
            widget.setEnabled(is_connected)

    def display_message(self, message, is_error=False):
        self.message_label.setText(message)
        self.message_label.setStyleSheet("color: red;" if is_error else "color: black;")

    def update_pump_status(self):
        # 펌프의 현재 상태를 읽어와 UI에 표시
        if self.pump_instance and self.connected:
            mode_val_raw = self.pump_instance.get_mode()
            self.current_mode_str = mode_val_raw
            mode_map = {"0": "Run Mode (0)", "1": "Dispense Vol/Time (1)", "2": "Dispense Rate/Time (2)"}
            self.current_mode_label.setText(mode_map.get(mode_val_raw, f"Read Error ({mode_val_raw})"))
            
            op_status_str = self.pump_instance.get_pump_status(1)
            motor_display_text, motor_style_sheet = "N/A", "color: black;"
            if op_status_str and op_status_str not in ["ACK", "NACK", None]:
                try:
                    is_running = (int(op_status_str) & 1) == 1
                    motor_display_text = "Running" if is_running else "Stopped"
                    motor_style_sheet = "color: green; font-weight: bold;" if is_running else "color: red; font-weight: bold;"
                except (ValueError, TypeError):
                    motor_display_text, motor_style_sheet = "Status Parse Err", "color: orange;"
            else:
                motor_display_text, motor_style_sheet = f"Read Error ({op_status_str})", "color: orange;"
            self.motor_status_label.setText(motor_display_text)
            self.motor_status_label.setStyleSheet(motor_style_sheet)
            
            flow_rate = self.pump_instance.get_flow_rate_run_mode()
            self.current_flow_rate_label.setText(f"{flow_rate} µl/min" if isinstance(flow_rate, int) else f"Read Error ({flow_rate})")

    def handle_connect_pump(self):
        # 펌프 연결/해제 로직
        try:
            from Src.Pump_Control import SimdosPump
        except ImportError:
            self.display_message("SimdosPump module not found.", is_error=True); return

        if not self.connected:
            port = self.port_edit.text()
            if not port: self.display_message("COM Port must be entered.",is_error=True); return
            self.pump_instance = SimdosPump(port=port, pump_address=self.default_config.get("address", "00"),
                pump_model=self.default_config.get("model", "SIMDOS10"), timeout=0.5)
            self.display_message(f"Connecting to {self.pump_name} on {port}...")
            QApplication.processEvents()
            if self.pump_instance.connect():
                self.connected = True; self.status_label.setText("Connected"); self._set_status_color(True)
                self.display_message(f"{self.pump_name} connection successful.")
                model_fw = self.pump_instance.get_pump_model_firmware()
                self.model_label.setText(model_fw if model_fw and model_fw not in ["ACK", "NACK"] else "Read Error")
                self.update_pump_status(); self.update_timer.start(self.update_timer_interval)
            else:
                self.status_label.setText("Connection Failed"); self._set_status_color(False)
                self.display_message(f"{self.pump_name} connection failed.",is_error=True); self.pump_instance = None
        else:
            if self.pump_instance: self.pump_instance.stop_pump(); self.pump_instance.disconnect()
            self.connected = False; self.pump_instance = None; self.status_label.setText("Disconnected")
            self._set_status_color(False)
            for label in [self.model_label, self.current_mode_label, self.motor_status_label, self.current_flow_rate_label]: label.setText("N/A")
            self.update_timer.stop(); self.display_message(f"{self.pump_name} disconnected.")
        self._update_ui_for_connection_state()
        self.connection_status_changed.emit(self.connected)
    
    def handle_start_pump(self):
        if self.pump_instance and self.connected:
            response = self.pump_instance.start_pump()
            self.display_message(f"{self.pump_name} {'started.' if response == 'ACK' else 'start failed.'}",is_error=(response != 'ACK'))
            self.update_pump_status()
    def handle_stop_pump(self):
        if self.pump_instance and self.connected:
            response = self.pump_instance.stop_pump()
            self.display_message(f"{self.pump_name} {'stopped.' if response == 'ACK' else 'stop failed.'}",is_error=(response != 'ACK'))
            self.update_pump_status()
    def handle_set_run_mode(self):
        if self.pump_instance and self.connected:
            response = self.pump_instance.set_mode(0)
            self.display_message(f"Set to 'Run Mode'.", is_error=(response != 'ACK'))
            self.update_pump_status()
    def handle_prime_pump(self):
        if self.pump_instance and self.connected:
            response = self.pump_instance.prime_pump(strokes=1)
            self.display_message(f"Prime command sent.", is_error=(not response))
            self.update_pump_status()
    def handle_set_flow_rate(self):
        if self.pump_instance and self.connected:
            try:
                flow_rate_ul_min = int(self.flow_rate_set_edit.text())
                response = self.pump_instance.set_flow_rate_run_mode(flow_rate_ul_min)
                self.display_message(f"Flow rate set to {flow_rate_ul_min} µl/min.", is_error=(response != 'ACK'))
                self.update_pump_status()
            except ValueError: self.display_message("Invalid flow rate value.", is_error=True)

    def closeEvent(self, event):
        self.update_timer.stop()
        if self.pump_instance and self.connected: self.pump_instance.disconnect()
        super().closeEvent(event)


class MainWindowUI:
    """메인 윈도우의 전체 UI를 생성하고 배치하는 클래스"""
    def setupUi(self, MainWindow):
        main_widget = QWidget()
        MainWindow.setCentralWidget(main_widget)
        top_layout = QVBoxLayout(main_widget)

        top_control_layout = QHBoxLayout()
        status_group = QGroupBox("Status")
        status_layout = QGridLayout(status_group)
        
        bold_style = "font-weight: bold;"
        MainWindow.status_channel_label = QLabel("Channel : N/A")
        MainWindow.status_channel_label.setStyleSheet(bold_style)
        status_layout.addWidget(MainWindow.status_channel_label, 0, 0, 1, 2)
        MainWindow.status_cycle_label = QLabel("Cycle Number : N/A")
        MainWindow.status_cycle_label.setStyleSheet(bold_style)
        status_layout.addWidget(MainWindow.status_cycle_label, 0, 2, 1, 2)
        MainWindow.status_step_label = QLabel("Step : N/A")
        MainWindow.status_step_label.setStyleSheet(bold_style)
        status_layout.addWidget(MainWindow.status_step_label, 0, 4, 1, 2)
        
        status_layout.addWidget(QLabel("Monitoring Channel:"), 1, 0)
        MainWindow.status_channel_combo = QComboBox()
        MainWindow.status_channel_combo.addItems([str(i) for i in range(1, 9)])
        MainWindow.status_channel_combo.setCurrentText("1")
        status_layout.addWidget(MainWindow.status_channel_combo, 1, 1)

        interval_layout = QHBoxLayout()
        interval_layout.addStretch(1)
        interval_layout.addWidget(QLabel("Update Interval (s):"))
        MainWindow.status_interval_edit = QLineEdit("2")
        MainWindow.status_interval_edit.setFixedWidth(40)
        interval_layout.addWidget(MainWindow.status_interval_edit)
        MainWindow.status_interval_set_button = QPushButton("Set")
        interval_layout.addWidget(MainWindow.status_interval_set_button)
        status_layout.addLayout(interval_layout, 1, 2, 1, 4)

        status_layout.addWidget(QLabel("CSV Data Directory:"), 2, 0)
        MainWindow.auto_csv_dir_edit = QLineEdit(MainWindow.DEFAULT_AUTO_CSV_DIR)
        status_layout.addWidget(MainWindow.auto_csv_dir_edit, 2, 1, 1, 4)
        MainWindow.auto_browse_csv_dir_button = QPushButton("Browse...")
        status_layout.addWidget(MainWindow.auto_browse_csv_dir_button, 2, 5)

        logging_group = QGroupBox("Logging")
        logging_layout = QHBoxLayout(logging_group)
        MainWindow.set_log_path_button = QPushButton("Set Log Path")
        logging_layout.addWidget(MainWindow.set_log_path_button)
        logging_layout.addStretch(1)
        logging_layout.addWidget(QLabel("Interval (s):"))
        MainWindow.log_interval_edit = QLineEdit("1")
        MainWindow.log_interval_edit.setFixedWidth(50)
        logging_layout.addWidget(MainWindow.log_interval_edit)
        MainWindow.master_toggle_logging_button = QPushButton("Record ON")
        MainWindow.master_toggle_logging_button.setFixedWidth(120)
        logging_layout.addWidget(MainWindow.master_toggle_logging_button)

        top_control_layout.addWidget(status_group, 2)
        top_control_layout.addWidget(logging_group, 1)
        top_layout.addLayout(top_control_layout)

        pumps_group = QGroupBox("Pump Controls")
        pumps_main_layout = QVBoxLayout(pumps_group)
        master_buttons_layout = QHBoxLayout()
        MainWindow.master_connect_all_button = QPushButton("🔗 Connect All")
        MainWindow.master_start_all_button = QPushButton("▶ Start All")
        MainWindow.master_stop_all_button = QPushButton("■ Stop All")
        master_buttons_layout.addWidget(MainWindow.master_connect_all_button)
        master_buttons_layout.addWidget(MainWindow.master_start_all_button)
        master_buttons_layout.addWidget(MainWindow.master_stop_all_button)
        pumps_main_layout.addLayout(master_buttons_layout)
        pump_widgets_layout = QHBoxLayout()
        MainWindow.pump_a_widget = PumpControlWidget("Pump A", MainWindow.DEFAULT_PUMP_CONFIGS["Pump_A"])
        MainWindow.pump_b_widget = PumpControlWidget("Pump B", MainWindow.DEFAULT_PUMP_CONFIGS["Pump_B"])
        pump_widgets_layout.addWidget(MainWindow.pump_a_widget)
        pump_widgets_layout.addWidget(MainWindow.pump_b_widget)
        pumps_main_layout.addLayout(pump_widgets_layout)
        top_layout.addWidget(pumps_group)

        bottom_grid_layout = QGridLayout()
        auto_flow_group = QGroupBox("Automatic Flow Control")
        auto_flow_layout = QGridLayout(auto_flow_group)
        auto_flow_layout.addWidget(QLabel("Ch. for Current (I):"), 0, 0)
        MainWindow.auto_channel_no_combo = QComboBox()
        MainWindow.auto_channel_no_combo.addItems([str(i) for i in range(1, 9)])
        MainWindow.auto_channel_no_combo.setCurrentText("1")
        auto_flow_layout.addWidget(MainWindow.auto_channel_no_combo, 0, 1)
        MainWindow.auto_toggle_control_button = QPushButton("Start Auto Control")
        auto_flow_layout.addWidget(MainWindow.auto_toggle_control_button, 0, 2, 1, 2)
        auto_flow_layout.addWidget(QLabel("MIN Flow Rate (µl/min):"), 1, 0)
        MainWindow.auto_min_flow_edit = QLineEdit("2640")
        auto_flow_layout.addWidget(MainWindow.auto_min_flow_edit, 1, 1)
        auto_flow_layout.addWidget(QLabel("MAX Flow Rate (µl/min):"), 1, 2)
        MainWindow.auto_max_flow_edit = QLineEdit("6540")
        auto_flow_layout.addWidget(MainWindow.auto_max_flow_edit, 1, 3)
        auto_flow_layout.addWidget(QLabel("Lambda Charge (λ_C):"), 2, 0)
        MainWindow.auto_lambda_c_edit = QLineEdit("4.5")
        auto_flow_layout.addWidget(MainWindow.auto_lambda_c_edit, 2, 1)
        auto_flow_layout.addWidget(QLabel("Lambda Discharge (λ_D):"), 2, 2)
        MainWindow.auto_lambda_d_edit = QLineEdit("4.5")
        auto_flow_layout.addWidget(MainWindow.auto_lambda_d_edit, 2, 3)
        auto_flow_layout.addWidget(QLabel("No. of Cells:"), 3, 0)
        MainWindow.auto_n_cell_edit = QLineEdit("1")
        auto_flow_layout.addWidget(MainWindow.auto_n_cell_edit, 3, 1)
        auto_flow_layout.addWidget(QLabel("Update Interval (s):"), 3, 2)
        MainWindow.auto_update_interval_edit = QLineEdit("10")
        auto_flow_layout.addWidget(MainWindow.auto_update_interval_edit, 3, 3)
        auto_flow_layout.addWidget(QLabel("Temp Sensors for Avg:"), 4, 0)
        temp_combo_layout = QHBoxLayout()
        MainWindow.temp_sensor_1_combo = QComboBox()
        MainWindow.temp_sensor_1_combo.addItems([f"A{i}" for i in range(5)])
        temp_combo_layout.addWidget(MainWindow.temp_sensor_1_combo)
        MainWindow.temp_sensor_2_combo = QComboBox()
        MainWindow.temp_sensor_2_combo.addItems([f"A{i}" for i in range(5)])
        MainWindow.temp_sensor_2_combo.setCurrentIndex(1)
        temp_combo_layout.addWidget(MainWindow.temp_sensor_2_combo)
        auto_flow_layout.addLayout(temp_combo_layout, 4, 1, 1, 2)
        MainWindow.avg_temp_display_label = QLabel("Avg Temp: N/A")
        MainWindow.avg_temp_display_label.setStyleSheet(bold_style)
        auto_flow_layout.addWidget(MainWindow.avg_temp_display_label, 4, 3)
        MainWindow.auto_control_status_label = QLabel("Status: Inactive.")
        MainWindow.auto_control_status_label.setStyleSheet("font-style: italic;")
        auto_flow_layout.addWidget(MainWindow.auto_control_status_label, 5, 0, 1, 4)
        bottom_grid_layout.addWidget(auto_flow_group, 0, 0)

        arduino_group = QGroupBox("Arduino Control")
        arduino_layout = QGridLayout(arduino_group)
        arduino_layout.addWidget(QLabel("Arduino COM Port:"), 0, 0)
        MainWindow.arduino_port_edit = QLineEdit(MainWindow.DEFAULT_ARDUINO_PORT)
        arduino_layout.addWidget(MainWindow.arduino_port_edit, 0, 1)
        MainWindow.arduino_connect_button = QPushButton("Connect")
        arduino_layout.addWidget(MainWindow.arduino_connect_button, 0, 2)
        MainWindow.arduino_status_label = QLabel("Status: Disconnected")
        MainWindow.arduino_status_label.setStyleSheet("font-weight: bold; color: red;")
        arduino_layout.addWidget(MainWindow.arduino_status_label, 0, 3)
        relay_button_layout = QHBoxLayout()
        MainWindow.valve_open_button = QPushButton("Valve Open")
        MainWindow.valve_open_button.setEnabled(False)
        MainWindow.valve_close_button = QPushButton("Valve Close")
        MainWindow.valve_close_button.setEnabled(False)
        relay_button_layout.addWidget(MainWindow.valve_open_button)
        relay_button_layout.addWidget(MainWindow.valve_close_button)
        arduino_layout.addLayout(relay_button_layout, 1, 0, 1, 4)
        
        
        # [UI 수정] 릴레이 자동 제어판 UI 구조 변경
        valve_group = QGroupBox("Rebalancing Valve (Charge Step Only)")
        valve_outer_layout = QVBoxLayout(valve_group)
        MainWindow.valve_auto_toggle_checkbox = QCheckBox("Enable Rebalancing")
        valve_outer_layout.addWidget(MainWindow.valve_auto_toggle_checkbox)
        
        MainWindow.valve_settings_container = QWidget() # 설정들을 담을 컨테이너
        valve_form_layout = QFormLayout(MainWindow.valve_settings_container)
        valve_form_layout.setContentsMargins(10, 5, 5, 5) # 들여쓰기 효과
        MainWindow.valve_base_cycle_edit = QLineEdit("1")
        MainWindow.valve_interval_edit = QLineEdit("5")
        MainWindow.valve_duration_edit = QLineEdit("1")
        valve_form_layout.addRow("Base Cycle:", MainWindow.valve_base_cycle_edit)
        valve_form_layout.addRow("Cycle Interval:", MainWindow.valve_interval_edit)
        valve_form_layout.addRow("Open Duration (min):", MainWindow.valve_duration_edit)
        valve_outer_layout.addWidget(MainWindow.valve_settings_container)
        arduino_layout.addWidget(valve_group, 2, 0, 1, 4)
        
        arduino_layout.addWidget(QLabel("Temperatures (°C):"), 3, 0)
        MainWindow.temp_display_labels = []
        temp_labels_layout = QHBoxLayout()
        for i in range(5):
            label = QLabel(f"A{i}: N/A")
            MainWindow.temp_display_labels.append(label)
            temp_labels_layout.addWidget(label)
        arduino_layout.addLayout(temp_labels_layout, 3, 1, 1, 3)
        MainWindow.arduino_message_label = QLabel("")
        MainWindow.arduino_message_label.setWordWrap(True)
        arduino_layout.addWidget(MainWindow.arduino_message_label, 4, 0, 1, 4)
        bottom_grid_layout.addWidget(arduino_group, 0, 1)

        logo_clock_container = QWidget()
        logo_clock_layout = QHBoxLayout(logo_clock_container)
        logo_clock_layout.addStretch(1)
        MainWindow.logo_label = QLabel()
        logo_clock_layout.addWidget(MainWindow.logo_label)
        MainWindow.clock_label = QLabel("00:00:00")
        clock_font = QFont(); clock_font.setPointSize(16); clock_font.setBold(True)
        MainWindow.clock_label.setFont(clock_font)
        logo_clock_layout.addWidget(MainWindow.clock_label)
        logo_clock_layout.addStretch(1)
        logo_clock_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        bottom_grid_layout.addWidget(logo_clock_container, 1, 1)
        
        pm_group = QGroupBox("Power Meter")
        pm_grid_layout = QGridLayout(pm_group)
        pm_grid_layout.addWidget(QLabel("COM Port:"), 0, 0)
        MainWindow.pm_port_edit = QLineEdit(MainWindow.DEFAULT_POWER_METER_PORT)
        pm_grid_layout.addWidget(MainWindow.pm_port_edit, 0, 1)
        MainWindow.pm_connect_button = QPushButton("Connect")
        pm_grid_layout.addWidget(MainWindow.pm_connect_button, 0, 2)
        MainWindow.pm_status_label = QLabel("Status: Disconnected")
        MainWindow.pm_status_label.setStyleSheet("font-weight: bold; color: red;")
        pm_grid_layout.addWidget(MainWindow.pm_status_label, 0, 3)
        pm_grid_layout.addWidget(QLabel("Current Power (W):"), 1, 0)
        MainWindow.pm_current_power_label = QLabel("N/A")
        pm_grid_layout.addWidget(MainWindow.pm_current_power_label, 1, 1, 1, 3)
        pm_grid_layout.addWidget(QLabel("Accumulated Energy (Wh):"), 2, 0)
        MainWindow.pm_accumulated_energy_label = QLabel("N/A")
        pm_grid_layout.addWidget(MainWindow.pm_accumulated_energy_label, 2, 1, 1, 3)
        MainWindow.pm_logging_status_label = QLabel("Logging: Inactive")
        MainWindow.pm_logging_status_label.setStyleSheet("font-style: italic;")
        pm_grid_layout.addWidget(MainWindow.pm_logging_status_label, 3, 0, 1, 4)
        MainWindow.pm_message_label = QLabel("")
        MainWindow.pm_message_label.setWordWrap(True)
        pm_grid_layout.addWidget(MainWindow.pm_message_label, 4, 0, 1, 4)
        bottom_grid_layout.addWidget(pm_group, 1, 0)
        
        bottom_grid_layout.setColumnStretch(0, 1)
        bottom_grid_layout.setColumnStretch(1, 1)
        bottom_grid_layout.setRowStretch(0, 1)
        bottom_grid_layout.setRowStretch(1, 0)

        top_layout.addLayout(bottom_grid_layout)
        MainWindow.adjustSize()