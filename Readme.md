# Single Cell Control Panel

**Single Cell Control Panel**은 PyQt6 기반의 GUI 애플리케이션으로, 다중 펌프, 전력계, Arduino를 연동하여 실험 과정을 자동화하고 모니터링하기 위해 개발되었습니다.

---

## 주요 기능

*   **펌프 제어**:
    *   두 개의 독립적인 펌프(A, B) 연결 및 상태 모니터링
    *   개별/전체 펌프 시작, 정지, 프라임(Prime) 기능
    *   실시간 유량(µl/min) 설정 및 확인

*   **자동 유량 제어**:
    *   전류(I), 개방 회로 전압(OCV) 값을 읽어 네른스트(Nernst) 방정식을 통해 실시간 SOC(State of Charge) 계산
    *   계산된 SOC와 설정된 람다(λ) 값을 기반으로 최적의 펌프 유량 자동 계산 및 설정

*   **밸브 및 온도 제어 (Arduino)**:
    *   Arduino 연결 및 상태 모니터링
    *   밸브(릴레이) 수동 개폐 제어
    *   **자동 밸브 제어**: 충전(Charge) 스텝의 특정 주기에 도달하면 설정된 시간 동안 밸브 리밸런싱
    *   다중 채널(5개) 온도 센서 값 실시간 모니터링

*   **전력 모니터링 (GW Instek GPM-8213)**:
    *   GW Instek GPM-8213 전력계 연동
    *   실시간 전력(W) 및 누적 에너지(Wh) 측정

*   **통합 데이터 로깅**:
    *   연결된 모든 장비(펌프, 전력계, 온도 센서, 밸브 상태)의 데이터를 타임스탬프와 함께 단일 CSV 파일로 기록
    *   로깅 주기(초 단위) 설정 가능

---

## 설치 및 실행 방법

### 1. 사전 요구사항
*   Python 3.8 이상
*   실험 장비 (Simdos 펌프, GPM-8213 전력계, Arduino 등)
*   각 장비에 맞는 시리얼(COM) 포트 연결

### 2. 설치 과정

```bash
# 1. 프로젝트 리포지토리를 복제합니다.
git clone https://github.com/H2-wsong/Single_Cell_Control_Panel.git
cd Single_Cell_Control_Panel

# 2. (권장) 가상 환경을 생성하고 활성화합니다.
python -m venv venv

# Windows
venv\Scripts\activate

# macOS/Linux
source venv/bin/activate

# 3. 필요한 라이브러리를 설치합니다.
pip install -r requirements.txt
```

### 3. 설정

애플리케이션 실행 전, 사용자의 하드웨어에 맞게 시리얼(COM) 포트를 설정해야 할 수 있습니다.

*   **설정 파일**: `main.py`
*   **설정 변수**: `DEFAULT_PUMP_CONFIGS`
*   **수정 내용**: Pump A와 Pump B의 `port` 값을 실제 연결된 COM 포트 번호로 수정합니다.

```python
# main.py 파일 내의 설정 예시
DEFAULT_PUMP_CONFIGS = {
    "Pump_A": {"port": "COM3", "address": "00", "model": "SIMDOS10", "flow_rate": "30000"},
    "Pump_B": {"port": "COM4", "address": "00", "model": "SIMDOS10", "flow_rate": "30000"}
}
```

### 4. 애플리케이션 실행

프로젝트 최상위 폴더에서 아래 명령어를 실행합니다.
```bash
python main.py
```

---

## 프로젝트 구조
```
/Single_Cell_Control_Panel/
├── main.py                     # 메인 실행 파일
├── Readme.md                   # 프로젝트 설명 문서
├── requirements.txt            # 필요 라이브러리 목록
└── Source/
    ├── __init__.py
    ├── gui.py                  # 메인 윈도우 및 UI 구성 요소
    ├── Pump_Control.py         # Simdos 펌프 제어 로직
    ├── Arduino.py              # Arduino 제어 로직 (밸브, 온도)
    └── PowerMeter_Control.py   # GPM-8213 전력계 제어 로직
```