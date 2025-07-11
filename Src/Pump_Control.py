import serial
import time
import csv
from datetime import datetime
import os

# 프로토콜 문서에서 정의된 제어 문자
STX = b'\x02'  # Start of Text
ETX = b'\x03'  # End of Text
ACK = b'\x06'  # Acknowledge
NACK = b'\x15' # Negative Acknowledge

# 필요한 경우, 범용 LRC를 위한 ASCII 'U'
UNIVERSAL_LRC_U = b'U' # 십진수 85

class SimdosPump:
    def __init__(self, port, baudrate=9600, pump_address="00", timeout=0.5, pump_model="SIMDOS10", base_log_path="."):
        """
        SimdosPump 컨트롤러를 초기화합니다.

        Args:
            port (str): 펌프의 COM 포트 (예: 'COM3').
            baudrate (int): 통신 보드레이트 (기본값은 9600).
            pump_address (str): 2자리 ASCII 펌프 주소.
            timeout (float): 시리얼 통신 타임아웃 (초 단위).
            pump_model (str, optional): "SIMDOS02" 또는 "SIMDOS10". 기본값은 "SIMDOS10".
            base_log_path (str): 로그 파일을 저장할 기본 디렉토리.
        """
        self.port = port
        self.baudrate = baudrate
        self.pump_address_str = pump_address
        self.timeout = timeout
        self.ser = None  # 시리얼 포트 객체
        self.pump_model = pump_model
        self.base_log_path = base_log_path

        # 유량 로깅 관련 속성
        self.csv_writer_flow = None
        self.csv_file_flow = None
        self.is_flow_logging_active = False # 유량 로깅 활성 상태


        # 펌프별 제한 (단위: µl/min)
        self.flow_rate_limits = {
            "SIMDOS10": {"min": 1000, "max": 100000}   # FEM1.10: 1.0 ~ 100 ml/min
        }
        self.current_pump_limits = None # 현재 펌프 모델의 유량 제한
        if self.pump_model and self.pump_model in self.flow_rate_limits:
            self.current_pump_limits = self.flow_rate_limits[self.pump_model]
            print(f"펌프 모델 설정: {self.pump_model}, 유량 제한: {self.current_pump_limits}")
        else:
            print(f"경고: 펌프 모델 '{self.pump_model}'을(를) 인식할 수 없거나, 해당하는 경우 기본 SIMDOS10 제한이 적용됩니다. 클라이언트에서 유량 제한을 엄격하게 사전 검증하지 않습니다.")
            if self.pump_model == "SIMDOS10":
                  self.current_pump_limits = self.flow_rate_limits["SIMDOS10"]


        # 인터페이스 파라미터
        self.data_bits = 8      # 데이터 비트: 8
        self.parity = 'N'       # 패리티: 없음 (No)
        self.stop_bits = 1      # 스톱 비트: 1

        if not os.path.exists(self.base_log_path):
            try:
                os.makedirs(self.base_log_path)
            except OSError as e:
                print(f"기본 로그 디렉토리 {self.base_log_path} 생성 오류: {e}. 로그는 현재 디렉토리에 저장됩니다.")
                self.base_log_path = "."


    def connect(self):
        """펌프와의 시리얼 연결을 설정합니다."""
        try:
            self.ser = serial.Serial(
                port=self.port,
                baudrate=self.baudrate,
                bytesize=serial.EIGHTBITS,      # 데이터 비트: 8
                parity=self.parity,             # 패리티: 없음 (No)
                stopbits=serial.STOPBITS_ONE,   # 스톱 비트: 1
                timeout=self.timeout
            )
            if self.ser.is_open: # 시리얼 포트가 열려 있다면
                print(f"{self.port}의 펌프에 {self.baudrate} 보드레이트로 성공적으로 연결되었습니다.")
                return True
            else:
                print(f"시리얼 포트 {self.port}를 열지 못했습니다.")
                return False
        except serial.SerialException as e: # 시리얼 연결 예외 발생 시
            print(f"{self.port}의 펌프 연결 중 오류 발생: {e}")
            self.ser = None
            return False

    def disconnect(self):
        """시리얼 연결을 닫습니다."""
        if self.is_flow_logging_active:     # 펌프 연결 해제 시 로깅이 중지되도록 보장
            self.stop_flow_logging()
        if self.ser and self.ser.is_open:   # 시리얼 포트 객체가 존재하고 열려 있다면
            self.ser.close()                # 시리얼 포트 닫기
            print(f"{self.port}의 펌프와의 연결이 끊어졌습니다.")
        self.ser = None

    def _calculate_lrc(self, message_bytes_for_lrc):
        """
        LRC(Longitudinal Redundancy Check)를 계산합니다.
        LRC는 STX부터 ETX까지 모든 바이트의 XOR 합입니다.

        Args:
            message_bytes_for_lrc (bytes): LRC를 계산할 바이트들 (STX + 주소 + 명령어 문자열 + ETX).

        Returns:
            bytes: 계산된 LRC 바이트.
        """
        lrc = 0
        for byte_val in message_bytes_for_lrc: # 각 바이트에 대해
            lrc ^= byte_val                    # XOR 연산 수행
        return bytes([lrc])

    def _build_command(self, command_string_ascii, use_universal_lrc=False):
        """
        STX, 주소, 명령어 문자열, ETX, LRC를 포함하는 전체 명령어 패킷을 생성합니다.

        Args:
            command_string_ascii (str): ASCII 명령어 문자열 (예: "MS0", "?RV").
            use_universal_lrc (bool): True이면 'U'를 LRC로 사용합니다.

        Returns:
            bytes: 전송할 전체 명령어 패킷.
        """
        address_bytes = self.pump_address_str.encode('ascii')   # 주소를 ASCII 바이트로 인코딩
        cmd_str_bytes = command_string_ascii.encode('ascii')    # 명령어 문자열을 ASCII 바이트로 인코딩

        bytes_for_lrc = STX + address_bytes + cmd_str_bytes + ETX # LRC 계산 대상 바이트들
        
        if use_universal_lrc: # 범용 LRC 사용 여부
            lrc_byte = UNIVERSAL_LRC_U # 'U' 사용
        else:
            lrc_byte = self._calculate_lrc(bytes_for_lrc) # LRC 계산
        
        full_command = bytes_for_lrc + lrc_byte # 전체 명령어 패킷
        return full_command

    def send_command(self, cmd_str_ascii, expect_data=False, use_universal_lrc_option=False):
        # cmd_str_ascii: 전송할 ASCII 명령어 문자열
        # expect_data: 데이터 응답을 기대하는지 여부
        # use_universal_lrc_option: 범용 LRC를 사용할지 여부
        if not self.ser or not self.ser.is_open: # 펌프가 연결되지 않았거나 포트가 열려있지 않으면
            print("펌프가 연결되지 않았습니다. 명령을 전송할 수 없습니다.")
            return None

        full_command_packet = self._build_command(cmd_str_ascii, use_universal_lrc=use_universal_lrc_option) # 전체 명령어 패킷 생성
        
        try:
            self.ser.reset_input_buffer()   # 입력 버퍼 비우기
            self.ser.reset_output_buffer()  # 출력 버퍼 비우기
            # print(f"펌프 ({self.pump_address_str})로 전송: {cmd_str_ascii} -> {full_command_packet.hex(' ').upper()}")
            self.ser.write(full_command_packet) # 명령어 패킷 전송
            
            first_byte = self.ser.read(1) # 응답의 첫 바이트 읽기
            if not first_byte: # 응답이 없으면
                # print(f"펌프로부터 명령어 '{cmd_str_ascii}'에 대한 응답 없음")
                return None 

            if first_byte == ACK: # 긍정 응답 (ACK, 십진수 6)
                if not expect_data: # 데이터 응답을 기대하지 않으면
                    return "ACK" # ACK 반환
                else: # ACK 후 STX 데이터 ETX LRC를 기대
                    response_packet_bytes = self.ser.read_until(ETX) # ETX까지 읽기
                    if not response_packet_bytes or not response_packet_bytes.endswith(ETX): # 응답 패킷이 ETX로 끝나지 않으면 (불완전)
                        print(f"'{cmd_str_ascii}'에 대한 ACK 후 불완전한 데이터 패킷. 수신: {response_packet_bytes.hex(' ')}")
                        return None
                    
                    lrc_received = self.ser.read(1) # 수신된 LRC 읽기
                    if not lrc_received: # LRC가 없으면
                        print(f"'{cmd_str_ascii}'에 대한 ACK 후 데이터 패킷에 LRC 누락.")
                        return None
                    
                    # LRC는 데이터 블록 (STX + 데이터 + ETX)에 대해 계산됨
                    calculated_lrc_on_recv = self._calculate_lrc(response_packet_bytes) # 수신된 데이터에 대한 LRC 계산
                    if calculated_lrc_on_recv != lrc_received: # 계산된 LRC와 수신된 LRC가 다르면
                        print(f"'{cmd_str_ascii}'에 대한 수신 데이터 패킷 LRC 불일치. 계산값: {calculated_lrc_on_recv.hex()}, 수신값: {lrc_received.hex()}")
                        return None 

                    if response_packet_bytes.startswith(STX) and response_packet_bytes.endswith(ETX): # 패킷이 STX로 시작하고 ETX로 끝나면
                        data_bytes = response_packet_bytes[len(STX):-len(ETX)] # STX와 ETX 사이의 데이터 추출
                        decoded_data = data_bytes.decode('ascii') # ASCII로 디코딩
                        return decoded_data # 디코딩된 데이터 반환
                    else:
                        print(f"'{cmd_str_ascii}'에 대한 ACK 후 잘못된 형식의 데이터 패킷. 패킷: {response_packet_bytes.hex(' ')}")
                        return None

            elif first_byte == NACK: # 부정 응답 (NACK, 십진수 21)
                print(f"명령어 '{cmd_str_ascii}'가 부정적으로 응답됨 (NACK).")
                return "NACK"
            
            else: # 예상치 못한 첫 바이트
                print(f"'{cmd_str_ascii}'에 대한 응답에서 예상치 못한 첫 바이트: {first_byte.hex()}")
                return None

        except serial.SerialTimeoutException: # 시리얼 타임아웃 예외
            print(f"펌프로부터 명령어 '{cmd_str_ascii}'에 대한 응답 대기 시간 초과")
            return None
        except Exception as e: # 기타 통신 오류
            print(f"명령어 '{cmd_str_ascii}' 통신 중 오류 발생: {e}")
            return None

    # --- 유량 로깅 메소드 ---
    def start_flow_logging(self, filename_prefix="FlowRateLog"):
        # filename_prefix: 로그 파일 이름 접두사
        if self.is_flow_logging_active: # 이미 로깅 중이면
            print("유량 로깅이 이미 활성화되어 있습니다.")
            return False
        
        current_time_str = datetime.now().strftime("%Y%m%d_%H%M%S") # 현재 시간 문자열
        csv_file_path = os.path.join(self.base_log_path, f"{filename_prefix}_{self.pump_address_str}_{current_time_str}.csv") # CSV 파일 경로 생성
        
        try:
            self.csv_file_flow = open(csv_file_path, mode='w', newline='', encoding='utf-8') # CSV 파일 열기 (쓰기 모드)
            self.csv_writer_flow = csv.writer(self.csv_file_flow) # CSV writer 객체 생성
            self.csv_writer_flow.writerow(['Timestamp', 'SetFlowRate_ul_min', 'PumpMode']) # 헤더 작성
            print(f"유량 로깅 시작: {csv_file_path}")
            self.is_flow_logging_active = True # 로깅 활성 상태로 변경
            return True
        except IOError as e: # 파일 입출력 오류 발생 시
            print(f"유량 CSV 로깅 시작 오류: {e}")
            self.is_flow_logging_active = False
            return False

    def log_one_flow_reading(self):
        if not self.is_flow_logging_active or not self.csv_writer_flow: # 로깅이 활성화되지 않았거나 writer가 초기화되지 않았으면
            # print("유량 로깅이 활성화되지 않았거나 writer가 초기화되지 않았습니다.") # 너무 많은 로그를 남길 수 있어 주석 처리
            return False
        
        current_set_flow_rate = self.get_flow_rate_run_mode() # 현재 설정된 유량 읽기 (RV 명령어)
        current_pump_mode = self.get_mode() # 현재 펌프 모드 읽기 (MS 명령어)
        
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3] # 타임스탬프 (밀리초까지)
        
        flow_rate_to_log = "N/A" # 로그에 기록할 유량 값
        if isinstance(current_set_flow_rate, int):
            flow_rate_to_log = current_set_flow_rate
        elif current_set_flow_rate == "NACK": # NACK 응답 시
             flow_rate_to_log = "NACK_ReadError" # 읽기 오류 (NACK)
        elif current_set_flow_rate is None: # None 응답 시 (타임아웃 등)
             flow_rate_to_log = "ReadError" # 읽기 오류


        mode_to_log = "N/A" # 로그에 기록할 펌프 모드
        if isinstance(current_pump_mode, str) and current_pump_mode not in ["ACK", "NACK", None]: # 유효한 모드 문자열인 경우
            try:
                mode_val = int(current_pump_mode) # 정수형으로 변환
                if mode_val == 0: mode_to_log = "Run" # 실행 모드
                elif mode_val == 1: mode_to_log = "Dispense_VolTime" # 분주 모드 (부피 및 시간)
                elif mode_val == 2: mode_to_log = "Dispense_RateTime" # 분주 모드 (유량 및 시간)
                else: mode_to_log = f"Unknown({mode_val})" # 알 수 없는 모드
            except ValueError: # 정수 변환 실패 시
                mode_to_log = f"ParseError({current_pump_mode})" # 파싱 오류
        elif current_pump_mode == "NACK":
            mode_to_log = "NACK_ReadError" # 읽기 오류 (NACK)
        elif current_pump_mode is None:
            mode_to_log = "ReadError" # 읽기 오류


        self.csv_writer_flow.writerow([timestamp, flow_rate_to_log, mode_to_log]) # CSV 파일에 한 줄 쓰기
        # print(f"유량 기록됨: {timestamp}, 설정 유량: {flow_rate_to_log}, 모드: {mode_to_log}") # 선택적 콘솔 출력 (주석 처리됨)
        return True

    def stop_flow_logging(self):
        if self.is_flow_logging_active and self.csv_file_flow: # 로깅이 활성화되어 있고 파일 객체가 존재하면
            self.csv_file_flow.close() # 파일 닫기
            self.csv_file_flow = None
            self.csv_writer_flow = None
            self.is_flow_logging_active = False # 로깅 비활성 상태로 변경
            print("유량 로깅이 중지되었습니다.")
        elif not self.is_flow_logging_active: # 로깅이 활성화되어 있지 않으면
            print("유량 로깅이 활성화되어 있지 않았습니다.")


    # --- 상위 수준 펌프 명령어 ---

    def check_communication(self):
        """통신 상태를 확인합니다."""
        response = self.send_command("?SI", expect_data=True) # ?SI: 통신 확인 기능
        if response and response not in ["ACK", "NACK"]: # ACK/NACK가 아닌 유효한 응답일 경우 (주소 반환)
            print(f"통신 확인 성공. 펌프로부터 받은 펌프 주소: {response}")
        return response

    def set_mode(self, mode_value): # MSn: 모드 선택
        # mode_value: 설정할 모드 값 (0, 1, 또는 2)
        if mode_value not in [0, 1, 2]:
            raise ValueError("잘못된 모드 값입니다. 0, 1, 또는 2여야 합니다.")
        # SIMDOS10의 경우, 모드 0 (실행 모드)은 일반적으로 연속 유량 제어에 사용됩니다.
        # 모드 0: 실행 모드 활성
        # 모드 1: 분주 모드 (ml 및 시간) 활성
        # 모드 2: 분주 모드 (ml/min 및 시간) 활성
        return self.send_command(f"MS{mode_value}", expect_data=False)

    def get_mode(self): # ?MS: 모드 읽기
        """현재 펌프 모드를 읽어옵니다."""
        return self.send_command("?MS", expect_data=True)

    def start_pump(self): # KYn, n=1 시작
        """펌프를 시작합니다."""
        return self.send_command("KY1", expect_data=False)

    def stop_pump(self): # KYn, n=0 정지
        """펌프를 정지합니다."""
        return self.send_command("KY0", expect_data=False)

    def prime_pump(self, strokes=1): # KYn, n=2 프라임/배출 (1 스트로크)
        # strokes: 프라이밍 스트로크 횟수
        """펌프를 프라이밍합니다 (기본 1 스트로크)."""
        print(f"펌프 프라이밍 중 ({strokes} 스트로크)...")
        ack_responses = []
        for _ in range(strokes):
            response = self.send_command("KY2", expect_data=False) # 프라임 명령어 전송
            ack_responses.append(response)
            if response != "ACK": # ACK 응답이 아니면
                print(f"프라임 스트로크 실패 또는 응답 없음: {response}")
                break # 중단
            time.sleep(0.5) # 스트로크 간 약간의 지연 (펌프 반응 시간 고려)
        return all(r == "ACK" for r in ack_responses) # 모든 스트로크가 ACK였는지 확인

    def set_flow_rate_run_mode(self, flow_rate_ul_min): # RVnnnnnnnn: 실행 모드 유량 µl/min
        # flow_rate_ul_min: 설정할 유량 (µl/min 단위)
        """실행 모드에서 펌프의 유량을 설정합니다 (µl/min)."""
        # SIMDOS10: 최소 1000 µl/min (1.0 ml/min), 최대 100000 µl/min (100.0 ml/min)
        if self.current_pump_limits: # 펌프 모델별 유량 제한이 설정되어 있으면
            if not (self.current_pump_limits["min"] <= flow_rate_ul_min <= self.current_pump_limits["max"]):
                print(f"경고: 유량 {flow_rate_ul_min} µl/min은(는) {self.pump_model}의 사전 구성된 제한 범위({self.current_pump_limits['min']}-{self.current_pump_limits['max']})를 벗어납니다.")
                # raise ValueError(f"유량 {flow_rate_ul_min} µl/min은(는) 펌프 모델의 범위를 벗어납니다.") # 필요시 예외 발생 (주석 처리)
        
        if not (0 <= flow_rate_ul_min <= 99999999): # 프로토콜 형식 제한 (8자리)
                 raise ValueError("유량은 명령어 형식을 위해 0과 99,999,999 사이여야 합니다.")
        
        command_str = f"RV{int(flow_rate_ul_min):08d}" # 8자리 숫자로 포맷팅 (앞부분 0으로 채움)
        return self.send_command(command_str, expect_data=False)

    def get_flow_rate_run_mode(self): # ?RV: 실행 모드 유량 읽기
        """실행 모드의 현재 설정된 유량을 읽어옵니다 (µl/min)."""
        response = self.send_command("?RV", expect_data=True)
        if response and response not in ["ACK", "NACK"]: # ACK/NACK가 아닌 유효한 응답일 경우
            try:
                return int(response) # 응답은 nnnnnnnn (8자리 숫자)
            except ValueError: # 정수 변환 실패 시
                print(f"응답으로부터 유량을 파싱할 수 없습니다: {response}")
                return None
        return response # ACK, NACK 또는 None 반환

    def get_pump_model_firmware(self): # ?SV: 펌프 모델 및 펌웨어 버전
        """펌프 모델 및 펌웨어 버전을 가져옵니다."""
        return self.send_command("?SV", expect_data=True) # 응답 pppppvvvvv

    def get_pump_status(self, status_type): # ?SSn: 펌프 상태 요청
        # status_type: 요청할 상태 유형 (1, 2, 3, 4, 또는 6)
        """특정 유형의 펌프 상태를 가져옵니다."""
        if status_type not in [1, 2, 3, 4, 6]: # ?SSn에 대한 유효한 n 값
            raise ValueError("잘못된 status_type입니다. 1, 2, 3, 4, 또는 6이어야 합니다.")
        return self.send_command(f"?SS{status_type}", expect_data=True) # 응답 nnn

    def reset_to_factory_settings(self): # IP: 펌프 공장 초기화
        """펌프를 공장 설정으로 초기화합니다."""
        print("경고: 펌프를 공장 설정으로 초기화하는 명령을 전송합니다.")
        return self.send_command("IP", expect_data=False)

    def initialize_pump(self): # IN: 펌프 초기화 (새로운 시작)
        """펌프를 초기화(재시작)합니다."""
        print("펌프를 초기화(재시작)하는 명령을 전송합니다.")
        return self.send_command("IN", expect_data=False)