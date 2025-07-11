class FakeSimdosPump:
    """
    실제 SimdosPump 클래스의 인터페이스를 완벽하게 흉내 내는 디버깅용 클래스.
    시리얼 통신 없이 내부 상태를 시뮬레이션하여 애플리케이션 로직을 테스트합니다.
    """
    def __init__(self, port, baudrate=9600, pump_address="00", timeout=0.5, pump_model="SIMDOS10", base_log_path="."):
        # __init__ 메소드는 실제 클래스와 동일한 인자를 받습니다.
        print(f"DEBUG: FakeSimdosPump created for port {port} with model {pump_model}")
        
        # 내부 상태 시뮬레이션을 위한 변수들
        self._port = port
        self._pump_address = pump_address
        self._is_connected = False
        self._is_running = False
        self._current_mode = "0"  # 'Run Mode'
        self._flow_rate = 30000   # µl/min
        self.is_flow_logging_active = False

        # 실제 클래스와 동일하게 펌프 모델별 제한을 설정합니다.
        self.pump_model = pump_model
        self.flow_rate_limits = {
            "SIMDOS10": {"min": 1000, "max": 100000}
        }
        self.current_pump_limits = self.flow_rate_limits.get(self.pump_model)
        if self.current_pump_limits:
             print(f"DEBUG: FakePump limits set for {pump_model}: {self.current_pump_limits}")

    # --- 연결 관리 메소드 ---
    def connect(self):
        print("DEBUG: FakeSimdosPump.connect() called.")
        self._is_connected = True
        return True  # 항상 연결 성공으로 처리

    def disconnect(self):
        print("DEBUG: FakeSimdosPump.disconnect() called.")
        self.stop_flow_logging() # 실제처럼 연결 해제 시 로깅 중지
        self._is_connected = False

    # --- 로깅 관리 메소드 ---
    def start_flow_logging(self, filename_prefix="FlowRateLog"):
        if self.is_flow_logging_active:
            print("DEBUG: Fake flow logging is already active.")
            return False
        print(f"DEBUG: Fake flow logging started with prefix '{filename_prefix}'.")
        self.is_flow_logging_active = True
        return True

    def log_one_flow_reading(self):
        # 이 함수는 타이머에 의해 계속 호출되므로, 너무 많은 출력을 피하기 위해 비워둡니다.
        # 필요 시 특정 조건에서만 print 하도록 수정할 수 있습니다.
        # if self._is_running:
        #     print(f"DEBUG: Faking a log entry. Flow: {self._flow_rate}, Mode: {self._current_mode}")
        pass
    
    def stop_flow_logging(self):
        if not self.is_flow_logging_active:
            return
        print("DEBUG: Fake flow logging stopped.")
        self.is_flow_logging_active = False

    # --- 상위 수준 펌프 명령어 메소드 ---
    def check_communication(self):
        print("DEBUG: FakeSimdosPump.check_communication() called.")
        return self._pump_address # 실제처럼 주소 반환

    def set_mode(self, mode_value):
        print(f"DEBUG: FakeSimdosPump.set_mode({mode_value}) called.")
        if mode_value not in [0, 1, 2]:
            return "NACK" # 실제처럼 잘못된 값에 NACK 반환
        self._current_mode = str(mode_value)
        return "ACK"

    def get_mode(self):
        # print("DEBUG: FakeSimdosPump.get_mode() called.") # 너무 자주 호출될 수 있음
        return self._current_mode

    def start_pump(self):
        print("DEBUG: FakeSimdosPump.start_pump() called.")
        if self._is_connected:
            self._is_running = True
            return "ACK"
        return "NACK"


    def stop_pump(self):
        print("DEBUG: FakeSimdosPump.stop_pump() called.")
        self._is_running = False
        return "ACK"

    def prime_pump(self, strokes=1):
        print(f"DEBUG: FakeSimdosPump.prime_pump({strokes} strokes) called.")
        return True # 항상 성공으로 처리

    def set_flow_rate_run_mode(self, flow_rate_ul_min):
        print(f"DEBUG: FakeSimdosPump.set_flow_rate_run_mode({flow_rate_ul_min}) called.")
        if not (0 <= flow_rate_ul_min <= 99999999):
            # 실제 클래스의 ValueError 대신 NACK을 반환하여 테스트
            return "NACK"
        self._flow_rate = int(flow_rate_ul_min)
        return "ACK"

    def get_flow_rate_run_mode(self):
        # print("DEBUG: FakeSimdosPump.get_flow_rate_run_mode() called.") # 너무 자주 호출될 수 있음
        return self._flow_rate

    def get_pump_model_firmware(self):
        print("DEBUG: FakeSimdosPump.get_pump_model_firmware() called.")
        return f"FAKE_{self.pump_model}_FW1.0" # 가짜 모델명과 펌웨어 버전 반환

    def get_pump_status(self, status_type):
        # print(f"DEBUG: FakeSimdosPump.get_pump_status({status_type}) called.") # 너무 자주 호출될 수 있음
        if status_type == 1: # 모터 상태 요청
            return "1" if self._is_running else "0"
        return "000" # 다른 상태 요청에는 기본값 반환

    def reset_to_factory_settings(self):
        print("WARNING: FakeSimdosPump.reset_to_factory_settings() called. (No action)")
        return "ACK"

    def initialize_pump(self):
        print("INFO: FakeSimdosPump.initialize_pump() called. (No action)")
        return "ACK"