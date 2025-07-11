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
            # 아두이노 보드가 리셋된 후 시리얼 통신이 안정화될 때까지 대기
            time.sleep(2)
            if self.ser.is_open:
                self.is_connected = True
                print(f"Successfully connected to Arduino on {self.port}.")
                # 아두이노로부터 초기 메시지를 읽어들여 연결 확인
                ready_msg = self.ser.readline().decode('utf-8', errors='ignore').strip()
                if "Ready" in ready_msg:
                    print(f"Arduino says: {ready_msg}")
                    return True
                else:
                    print(f"Warning: Arduino did not send ready signal. Received: {ready_msg}")
                    # 준비 신호가 없어도 연결은 된 것으로 간주할 수 있음
                    return True
        except serial.SerialException as e:
            print(f"Error connecting to Arduino on {self.port}: {e}")
            self.ser = None
            self.is_connected = False
            return False
        return False

    def disconnect(self):
        """아두이노와의 연결을 해제합니다."""
        if self.ser and self.ser.is_open:
            try:
                # 연결 종료 전 릴레이를 안전한 상태(닫힘)로 변경
                self.close_relay()
                time.sleep(0.1)
            except Exception as e:
                print(f"Error while setting relay to default state on disconnect: {e}")
            finally:
                self.ser.close()
                print("Disconnected from Arduino.")
        self.is_connected = False

    def _send_command(self, command):
        """아두이노로 명령을 보내고 응답을 읽습니다."""
        if not self.is_connected or not self.ser:
            print("Arduino is not connected.")
            return None
        try:
            self.ser.reset_input_buffer() # 이전 수신 데이터가 남아있는 것을 방지
            self.ser.write(command.encode('utf-8'))
            response = self.ser.readline().decode('utf-8', errors='ignore').strip()
            return response
        except serial.SerialException as e:
            print(f"Serial communication error with Arduino: {e}")
            self.disconnect() # 통신 오류 발생 시 연결 해제
            return None
        except Exception as e:
            print(f"An error occurred: {e}")
            return None

    def open_relay(self):
        """릴레이를 켜는(열림) 명령 '1'을 전송합니다."""
        return self._send_command('1')

    def close_relay(self):
        """릴레이를 끄는(닫힘) 명령 '0'을 전송합니다."""
        return self._send_command('0')

    def get_temperature(self, channel):
        """
        지정된 채널의 온도 센서 값을 요청합니다.
        channel (int): 0-3 사이의 센서 채널 번호.
        """
        if not (0 <= channel <= 3):
            print(f"Error: Invalid temperature channel {channel}. Must be 0-3.")
            return None
        
        # 채널 번호(0-3)를 고유 명령어('a'-'d')로 변환
        commands = ['a', 'b', 'c', 'd']
        command = commands[channel]
        
        response = self._send_command(command)
        
        if response is None:
            return None # 통신 실패
            
        try:
            # 아두이노에서 "24.57"과 같은 문자열로 응답하므로 float으로 변환
            return float(response)
        except (ValueError, TypeError):
            # 숫자로 변환할 수 없는 응답 (예: "Sensor_Error")이 올 경우 오류 처리
            print(f"Could not parse temperature from Arduino for channel {channel}. Response: '{response}'")
            return None
