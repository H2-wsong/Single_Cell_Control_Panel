import serial
import time
import csv
from datetime import datetime
import os

class GPM8213PowerMeter:
    """
    Controls a GW Instek GPM-8213 Power Meter via RS232 serial communication.
    """
    def __init__(self, port, baudrate=115200, timeout=1):
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self.ser = None
        self.is_connected = False
        
        self.csv_writer_pm = None
        self.csv_file_pm = None
        self.is_pm_logging_active = False
        self.base_log_path = "."

    def connect(self):
        if self.is_connected:
            print("Power Meter is already connected.")
            return True
        try:
            self.ser = serial.Serial(self.port, self.baudrate, timeout=self.timeout)
            if self.ser.is_open:
                self.is_connected = True
                print(f"Successfully connected to Power Meter on {self.port}.")
                return True
            else:
                print(f"Failed to open serial port {self.port} for Power Meter.")
                self.is_connected = False
                return False
        except serial.SerialException as e:
            print(f"Error connecting to Power Meter on {self.port}: {e}")
            self.ser = None
            self.is_connected = False
            return False

    def disconnect(self):
        if self.is_pm_logging_active:
            self.stop_pm_logging()
        if self.ser and self.ser.is_open:
            self.ser.close()
            print(f"Disconnected from Power Meter on {self.port}.")
        self.is_connected = False
        self.ser = None

    def _send_command(self, command, read_response=False, delay=0.1):
        if not self.is_connected or not self.ser:
            print("Power Meter not connected. Cannot send command.")
            return None
        try:
            self.ser.reset_input_buffer()
            self.ser.write(command.encode('ascii'))
            time.sleep(delay) # 중요: 명령어 처리 대기 시간
            if read_response:
                response = self.ser.readline().decode('ascii', errors='ignore').strip()
                return response
            return "OK" # 명령 전송 성공 (응답 안 읽는 경우)
        except serial.SerialException as e:
            print(f"Serial communication error with Power Meter: {e}")
            # Attempt to reconnect or handle error appropriately
            self.disconnect() # Consider attempting to reconnect
            return None
        except Exception as e:
            print(f"Error sending command to Power Meter '{command.strip()}': {e}")
            return None

    def setup_meter(self):
        if not self.is_connected: return False
        print("Setting up Power Meter GPM-8213...")
        # 헤더 미포함, Verbose 모드 OFF
        self._send_command(":COMMunicate:HEADer OFF\r\n")
        self._send_command(":COMMunicate:VERBose OFF\r\n")

        # 측정 항목 설정: 1.전압(Vrms), 2.전류(Irms), 3.유효전력(P), 4.누적전력량(WH)
        #
        self._send_command(":NUMeric:NORMal:ITEM1 U\r\n")    # Voltage (Vrms)
        self._send_command(":NUMeric:NORMal:ITEM2 I\r\n")    # Current (Irms)
        self._send_command(":NUMeric:NORMal:ITEM3 P\r\n")    # Active Power (W)
        self._send_command(":NUMeric:NORMal:ITEM4 WH\r\n")   # Watt-hour (likely mWh from meter)
        self._send_command(":NUMeric:NORMal:NUMBer 4\r\n")   # :NUMeric:NORMal:VALue? 가 4개 항목 반환하도록 설정
        
        # 적분기 기본 설정 (수동 모드, 와트시)
        self._send_command(":INTegrate:MODE MANUal\r\n") #
        self._send_command(":INTegrate:FUNCtion WATT\r\n") #
        print("Power Meter setup complete.")
        return True

    def get_readings(self):
        """ Fetches Voltage, Current, Power, and Accumulated Energy (WH). """
        if not self.is_connected: return None
        
        response_line = self._send_command(":NUMeric:NORMal:VALue?\r\n", read_response=True) #
        
        if response_line:
            values_str = response_line.split(',')
            if len(values_str) >= 4: # U, I, P, WH
                try:
                    voltage = float(values_str[0]) if values_str[0].lower() != 'nan' else 0.0
                    current = float(values_str[1]) if values_str[1].lower() != 'nan' else 0.0
                    power = float(values_str[2]) if values_str[2].lower() != 'nan' else 0.0
                    acc_energy_wh = float(values_str[3]) if values_str[3].lower() != 'nan' else 0.0
                    
                    return {
                        "voltage": voltage, "current": current,
                        "power": power, "energy_wh": acc_energy_wh
                    }
                except ValueError:
                    print(f"Power Meter data conversion error: {values_str}")
                    return None
            else:
                print(f"Power Meter received unexpected data format: {response_line}")
                return None
        else:
            # print("No data received from Power Meter.") # Can be noisy
            return None

    def start_energy_accumulation(self):
        """ Resets and starts the energy integrator. """
        if not self.is_connected: return False
        print("Starting Power Meter energy accumulation (reset and start).")
        self._send_command(":INTegrate:RESet\r\n") #
        time.sleep(0.2) # 리셋 후 안정화 시간
        resp = self._send_command(":INTegrate:STARt\r\n") #
        return resp is not None

    def stop_energy_accumulation(self):
        """ Stops the energy integrator. """
        if not self.is_connected: return False
        print("Stopping Power Meter energy accumulation.")
        resp = self._send_command(":INTegrate:STOP\r\n") #
        return resp is not None

    def reset_integrator(self): # 별도 리셋 (필요시 사용)
        if not self.is_connected: return False
        self._send_command(":INTegrate:RESet\r\n") #
        print("Power Meter integrator reset.")
        return True

    # --- Logging Methods ---
    def start_pm_logging(self, base_log_path, filename_prefix="PowerLog"):
        if self.is_pm_logging_active:
            print("Power Meter logging is already active.")
            return False
        
        self.base_log_path = base_log_path # GUI에서 설정된 경로 사용
        current_time_str_file = datetime.now().strftime("%Y%m%d_%H%M%S")
        csv_file_path = os.path.join(self.base_log_path, f"{filename_prefix}_{current_time_str_file}.csv")
        
        try:
            self.csv_file_pm = open(csv_file_path, mode='w', newline='', encoding='utf-8')
            self.csv_writer_pm = csv.writer(self.csv_file_pm)
            self.csv_writer_pm.writerow(['Timestamp', 'Voltage (V)', 'Current (A)', 'Power (W)', 'AccumulatedEnergy (Wh)'])
            print(f"Power Meter logging started to: {csv_file_path}")
            self.is_pm_logging_active = True
            return True
        except IOError as e:
            print(f"Error starting Power Meter CSV logging: {e}")
            self.is_pm_logging_active = False
            return False

    def log_pm_reading(self, timestamp, voltage, current, power, acc_energy_wh):
        if not self.is_pm_logging_active or not self.csv_writer_pm:
            return False
        
        self.csv_writer_pm.writerow([timestamp, voltage, current, power, acc_energy_wh])
        return True

    def stop_pm_logging(self):
        if self.is_pm_logging_active and self.csv_file_pm:
            self.csv_file_pm.close()
            self.csv_file_pm = None
            self.csv_writer_pm = None
            self.is_pm_logging_active = False
            print("Power Meter logging stopped.")
        elif not self.is_pm_logging_active:
            print("Power Meter logging was not active.")