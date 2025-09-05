import serial
import time

class ArduinoControl:
    """
    아두이노와 시리얼 통신을 통해 릴레이와 센서를 제어하는 클래스.
    """
    def __init__(self, port, baudrate=9600, timeout=1):
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self.ser = None
        self.is_connected = False

    def connect(self):
        """아두이노와 시리얼 포트 연결을 시도합니다."""
        try:
            self.ser = serial.Serial(self.port, self.baudrate, timeout=self.timeout)
            time.sleep(2) # 아두이노가 리셋 후 안정화될 시간을 줍니다.
            if self.ser.is_open:
                self.is_connected = True
                print(f"Successfully connected to Arduino on {self.port}.")
                # 아두이노로부터 "Ready" 신호를 기다립니다.
                ready_msg = self.ser.readline().decode('utf-8', errors='ignore').strip()
                if "Ready" in ready_msg:
                    print(f"Arduino says: {ready_msg}")
                    return True
                else:
                    print(f"Warning: Arduino did not send ready signal. Received: {ready_msg}")
                    return True # 연결은 되었으므로 True를 반환할 수 있습니다.
        except serial.SerialException as e:
            print(f"Error connecting to Arduino on {self.port}: {e}")
            self.ser = None
            self.is_connected = False
            return False
        return False

    def disconnect(self):
        """아두이노와의 연결을 해제합니다."""
        if self.ser and self.ser.is_open:
            self.ser.close()
            print("Disconnected from Arduino.")
        self.is_connected = False

    def _send_command(self, command):
        """아두이노로 명령을 보내고 응답을 읽습니다."""
        if not self.is_connected or not self.ser:
            # print("Arduino is not connected.") # This can be noisy
            return None
        try:
            self.ser.reset_input_buffer()
            self.ser.write(command.encode('utf-8'))
            response = self.ser.readline().decode('utf-8', errors='ignore').strip()
            return response
        except serial.SerialException as e:
            print(f"Serial communication error with Arduino: {e}")
            self.disconnect()
            return None
        except Exception as e:
            print(f"An error occurred: {e}")
            return None

    def open_valve(self):
        """릴레이를 활성화하여 밸브를 엽니다. 아두이노 명령 '1'을 전송"""
        return self._send_command('1')

    def close_valve(self):
        """릴레이를 비활성화하여 밸브를 닫습니다. 아두이노 명령 '0'을 전송"""
        return self._send_command('0')

    def get_priming_sensor_status(self):
        """프라이밍 센서 상태를 요청합니다. 아두이노 명령 'f'를 전송"""
        response = self._send_command('f')
        if response:
            return response
        return "Error"

    def get_temperature(self, channel):
        """
        지정된 채널의 온도 센서 값을 요청합니다.
        channel (int): 0-4 사이의 센서 채널 번호.
        """
        if not (0 <= channel <= 4):
            print(f"Error: Invalid temperature channel {channel}. Must be 0-4.")
            return None
        
        commands = ['a', 'b', 'c', 'd', 'e']
        command = commands[channel]
        
        response = self._send_command(command)
        
        if response is None:
            return None
            
        try:
            return float(response)
        except (ValueError, TypeError):
            # 아두이노가 'Sensor_Error' 같은 텍스트를 보내면 이 메시지가 출력됩니다.
            # print(f"Could not parse temperature from Arduino for channel {channel}. Response: '{response}'")
            return None