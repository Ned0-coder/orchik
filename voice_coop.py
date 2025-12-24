import streamlit as st
import pyaudio
import numpy as np
import time
import threading
import socket
import pickle
import pyautogui
import warnings
import sys

warnings.filterwarnings("ignore")

# Настройки
CHUNK = 1024
FORMAT = pyaudio.paInt16
CHANNELS = 1
RATE = 44100

# Конфигурация сети
PORT = 12345


class AudioProcessor:
    def __init__(self):
        self.audio = None
        self.stream = None
        self.is_recording = False
        self.audio_data = None
        self.lock = threading.Lock()
        
    def initialize_audio(self):
        """Инициализация аудио (ленивая загрузка)"""
        if self.audio is None:
            try:
                self.audio = pyaudio.PyAudio()
                return True
            except Exception as e:
                st.error(f"Ошибка инициализации аудио: {e}")
                return False
        return True

    def start_recording(self):
        if not self.initialize_audio():
            return False
            
        if self.stream is None:
            try:
                self.stream = self.audio.open(
                    format=FORMAT,
                    channels=CHANNELS,
                    rate=RATE,
                    input=True,
                    frames_per_buffer=CHUNK,
                    stream_callback=self.callback
                )
            except Exception as e:
                st.error(f"Ошибка микрофона: {e}")
                return False

        self.is_recording = True
        self.stream.start_stream()
        return True

    def callback(self, in_data, frame_count, time_info, status):
        with self.lock:
            self.audio_data = np.frombuffer(in_data, dtype=np.int16)
        return (in_data, pyaudio.paContinue)

    def get_audio_data(self):
        with self.lock:
            return self.audio_data

    def stop_recording(self):
        self.is_recording = False
        if self.stream:
            try:
                self.stream.stop_stream()
                self.stream.close()
            except:
                pass
            self.stream = None

    def cleanup(self):
        self.stop_recording()
        if self.audio:
            try:
                self.audio.terminate()
            except:
                pass
            self.audio = None


class NetworkClient:
    """Игрок который орет в микрофон - подключается к серверу"""

    def __init__(self):
        self.socket = None
        self.is_connected = False
        self.receive_thread = None
        self.server_address = ""

    def connect_to_server(self, server_ip):
        try:
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.socket.settimeout(5)
            
            # Обработка localhost
            if server_ip == "localhost":
                server_ip = "127.0.0.1"
                
            self.socket.connect((server_ip, PORT))
            self.socket.settimeout(None)
            self.is_connected = True
            self.server_address = server_ip

            st.success(f"✅ Успешно подключено к {server_ip}")
            return True
        except Exception as e:
            st.error(f"Ошибка подключения к {server_ip}: {e}")
            return False

    def send_key_press(self, key_data):
        """Отправляет команду на нажатие клавиши на сервер"""
        if not self.is_connected or self.socket is None:
            return False

        try:
            self.socket.sendall(pickle.dumps(key_data))
            return True
        except Exception as e:
            print(f"Ошибка отправки: {e}")
            self.is_connected = False
            return False

    def disconnect(self):
        self.is_connected = False
        if self.socket:
            try:
                self.socket.close()
            except:
                pass
            self.socket = None


class NetworkServer:
    """Игрок который получает нажатия - запускает сервер"""

    def __init__(self):
        self.server_socket = None
        self.clients = []
        self.is_running = False
        self.server_thread = None
        self.lock = threading.Lock()
        self.local_ip = "127.0.0.1"

    def get_local_ip(self):
        """Получение локального IP адреса"""
        try:
            # Альтернативный способ получения IP
            hostname = socket.gethostname()
            ip_address = socket.gethostbyname(hostname)
            if ip_address.startswith("127."):
                # Если это localhost, пробуем другой способ
                s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                try:
                    # doesn't even have to be reachable
                    s.connect(('10.255.255.255', 1))
                    ip_address = s.getsockname()[0]
                except Exception:
                    ip_address = '127.0.0.1'
                finally:
                    s.close()
            self.local_ip = ip_address
            return ip_address
        except:
            self.local_ip = "127.0.0.1"
            return "127.0.0.1"

    def start_server(self):
        try:
            self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.server_socket.bind(('0.0.0.0', PORT))  # Слушаем все интерфейсы
            self.server_socket.listen(5)
            self.server_socket.settimeout(1.0)  # Таймаут для accept
            self.is_running = True

            def accept_clients():
                while self.is_running:
                    try:
                        client_socket, addr = self.server_socket.accept()
                        client_socket.settimeout(0.1)
                        with self.lock:
                            self.clients.append({
                                'socket': client_socket,
                                'address': addr,
                                'connected': True
                            })
                        print(f"Новое подключение от {addr[0]}:{addr[1]}")
                    except socket.timeout:
                        continue
                    except:
                        if self.is_running:
                            print("Ошибка accept клиента")
                        break

            self.server_thread = threading.Thread(target=accept_clients)
            self.server_thread.daemon = True
            self.server_thread.start()

            # Запускаем поток обработки команд
            process_thread = threading.Thread(target=self.process_commands)
            process_thread.daemon = True
            process_thread.start()

            return True
        except Exception as e:
            st.error(f"Ошибка запуска сервера: {e}")
            return False

    def process_commands(self):
        """Обработка входящих команд и нажатие клавиш"""
        while self.is_running:
            disconnected = []
            with self.lock:
                for i, client in enumerate(self.clients):
                    if client['connected']:
                        try:
                            data = client['socket'].recv(4096)
                            if data:
                                try:
                                    command = pickle.loads(data)
                                    # Нажимаем клавишу
                                    if command.get('type') == 'key_press':
                                        key = command.get('key', '')
                                        if key:
                                            try:
                                                pyautogui.press(key)
                                                print(f"Нажата клавиша: {key}")
                                            except Exception as e:
                                                print(f"Ошибка нажатия {key}: {e}")
                                    elif command.get('type') == 'hotkey':
                                        keys = command.get('keys', [])
                                        if keys and len(keys) >= 2:
                                            try:
                                                pyautogui.hotkey(*keys)
                                                print(f"Нажата комбинация: {keys}")
                                            except Exception as e:
                                                print(f"Ошибка комбинации {keys}: {e}")
                                except Exception as e:
                                    print(f"Ошибка десериализации: {e}")
                        except socket.timeout:
                            pass
                        except Exception as e:
                            print(f"Ошибка получения данных: {e}")
                            client['connected'] = False
                            disconnected.append(i)

            # Удаляем отключенных клиентов
            if disconnected:
                with self.lock:
                    for idx in sorted(disconnected, reverse=True):
                        try:
                            self.clients[idx]['socket'].close()
                        except:
                            pass
                        self.clients.pop(idx)

            time.sleep(0.01)

    def get_connected_clients(self):
        """Возвращает список подключенных клиентов"""
        with self.lock:
            return [c for c in self.clients if c['connected']]

    def refresh_connection(self):
        """Обновляет состояние подключений"""
        disconnected = []
        with self.lock:
            for i, client in enumerate(self.clients):
                if client['connected']:
                    try:
                        # Проверяем соединение
                        client['socket'].send(b'ping')
                    except:
                        client['connected'] = False
                        disconnected.append(i)

            for idx in sorted(disconnected, reverse=True):
                try:
                    self.clients[idx]['socket'].close()
                except:
                    pass
                self.clients.pop(idx)

    def stop_server(self):
        self.is_running = False
        with self.lock:
            for client in self.clients:
                try:
                    client['socket'].close()
                except:
                    pass
            self.clients.clear()

        if self.server_socket:
            try:
                self.server_socket.close()
            except:
                pass
            self.server_socket = None


def calculate_volume(audio_data):
    if audio_data is None or len(audio_data) == 0:
        return -100

    try:
        audio_float = audio_data.astype(np.float32)
        rms = np.sqrt(np.mean(audio_float ** 2))

        if rms > 0:
            db = 20 * np.log10(rms / 32768.0)
        else:
            db = -100
        return db
    except:
        return -100


def main():
    st.set_page_config(
        page_title="Voice Co-op Controller",
        page_icon="🎮",
        layout="wide"
    )

    # Инициализация состояния
    if 'processor' not in st.session_state:
        st.session_state.processor = AudioProcessor()
    if 'server' not in st.session_state:
        st.session_state.server = NetworkServer()
    if 'client' not in st.session_state:
        st.session_state.client = NetworkClient()
    if 'mode' not in st.session_state:
        st.session_state.mode = "solo"
    if 'app_running' not in st.session_state:
        st.session_state.app_running = True

    # CSS для стилей
    st.markdown("""
    <style>
    .big-button {
        height: 100px;
        font-size: 24px !important;
        margin: 10px 0;
    }
    .status-box {
        padding: 20px;
        border-radius: 10px;
        margin: 10px 0;
    }
    .connected {
        background-color: #d4edda;
        border: 2px solid #c3e6cb;
    }
    .disconnected {
        background-color: #f8d7da;
        border: 2px solid #f5c6cb;
    }
    .active {
        background-color: #fff3cd;
        border: 2px solid #ffeaa7;
    }
    .waiting {
        background-color: #cce5ff;
        border: 2px solid #b8daff;
    }
    .server-info {
        background-color: #e2e3e5;
        border-left: 5px solid #6c757d;
        padding: 15px;
        border-radius: 5px;
        margin: 10px 0;
    }
    .stButton > button {
        width: 100%;
    }
    </style>
    """, unsafe_allow_html=True)

    # Заголовок
    st.title("🎮 Голосовой Co-op Controller")
    st.markdown("---")

    # Выбор режима
    col_mode1, col_mode2 = st.columns(2)

    with col_mode1:
        if st.button("🎯 ОДИНОЧНЫЙ РЕЖИМ",
                     use_container_width=True,
                     type="primary" if st.session_state.mode == "solo" else "secondary",
                     help="Один игрок, один микрофон, одна кнопка"):
            st.session_state.mode = "solo"
            # Останавливаем всё при смене режима
            st.session_state.processor.stop_recording()
            st.session_state.server.stop_server()
            st.session_state.client.disconnect()
            st.rerun()

    with col_mode2:
        if st.button("👥 КООПЕРАТИВНЫЙ РЕЖИМ",
                     use_container_width=True,
                     type="primary" if st.session_state.mode == "coop" else "secondary",
                     help="Один кричит, другой получает нажатия"):
            st.session_state.mode = "coop"
            # Останавливаем всё при смене режима
            st.session_state.processor.stop_recording()
            st.session_state.server.stop_server()
            st.session_state.client.disconnect()
            st.rerun()

    st.markdown("---")

    if st.session_state.mode == "solo":
        # ОДИНОЧНЫЙ РЕЖИМ
        solo_interface()
    else:
        # КООПЕРАТИВНЫЙ РЕЖИМ
        coop_interface()
        
    # Кнопка для принудительной остановки всего
    st.markdown("---")
    if st.button("🛑 АВАРИЙНАЯ ОСТАНОВКА", type="secondary"):
        st.session_state.processor.stop_recording()
        st.session_state.server.stop_server()
        st.session_state.client.disconnect()
        st.session_state.app_running = False
        st.success("Все процессы остановлены")
        st.rerun()


def solo_interface():
    """Интерфейс одиночного режима"""
    st.subheader("🎯 Настройки одиночного режима")

    col1, col2 = st.columns(2)

    with col1:
        button_input = st.text_input(
            "Кнопка для нажатия:",
            value="space",
            help="Например: space, enter, a, 1, f1, ctrl+c"
        )

    with col2:
        threshold = st.slider(
            "Порог громкости:",
            min_value=-50,
            max_value=0,
            value=-20,
            help="Чем выше значение, тем чувствительнее"
        )

    # Управление
    col_start, col_stop, col_status = st.columns([1, 1, 2])

    with col_start:
        if st.button("▶️ ЗАПУСТИТЬ", type="primary", use_container_width=True):
            if button_input.strip():
                if st.session_state.processor.start_recording():
                    st.success("✅ Микрофон активирован!")
                    time.sleep(0.5)
                    st.rerun()

    with col_stop:
        if st.button("⏹️ ОСТАНОВИТЬ", type="secondary", use_container_width=True):
            st.session_state.processor.stop_recording()
            st.info("⏸️ Микрофон выключен")
            time.sleep(0.5)
            st.rerun()

    with col_status:
        if st.session_state.processor.is_recording:
            st.markdown('<div class="status-box active">🎤 МИКРОФОН АКТИВЕН</div>', unsafe_allow_html=True)
        else:
            st.markdown('<div class="status-box disconnected">⏸️ МИКРОФОН ВЫКЛЮЧЕН</div>', unsafe_allow_html=True)

    # Мониторинг
    if st.session_state.processor.is_recording:
        st.markdown("---")

        vol_col, status_col = st.columns(2)

        with vol_col:
            vol_display = st.empty()

        with status_col:
            trigger_display = st.empty()

        # Цикл обработки
        last_press_time = 0
        max_iterations = 1000  # Защита от бесконечного цикла
        
        iteration = 0
        while st.session_state.processor.is_recording and iteration < max_iterations:
            iteration += 1
            
            audio_data = st.session_state.processor.get_audio_data()

            if audio_data is not None:
                current_volume = calculate_volume(audio_data)

                # Отображение громкости
                with vol_display:
                    if current_volume > threshold:
                        st.metric("🔊 ГРОМКОСТЬ", f"{current_volume:.1f} дБ", delta="ГРОМКО")
                    else:
                        st.metric("🔈 ГРОМКОСТЬ", f"{current_volume:.1f} дБ")

                # Проверка триггера
                current_time = time.time()

                if current_volume > threshold and (current_time - last_press_time) > 0.5:
                    with trigger_display:
                        st.warning("⚡ СРАБАТЫВАНИЕ...")

                    try:
                        if '+' in button_input:
                            keys = [k.strip() for k in button_input.split('+')]
                            pyautogui.hotkey(*keys)
                            action_text = f"Комбинация: {'+'.join(keys)}"
                        else:
                            pyautogui.press(button_input)
                            action_text = f"Кнопка: {button_input}"

                        last_press_time = current_time

                        with trigger_display:
                            st.success(f"✅ {action_text}")
                        time.sleep(0.3)

                    except Exception as e:
                        with trigger_display:
                            st.error(f"❌ Ошибка: {str(e)[:50]}")

                else:
                    with trigger_display:
                        if current_volume > threshold:
                            time_left = 0.5 - (current_time - last_press_time)
                            if time_left > 0:
                                st.info(f"⏳ Жду {time_left:.1f} сек")
                            else:
                                st.info("🔔 ГОТОВО К НАЖАТИЮ")
                        else:
                            st.info("🔈 ГОВОРИТЕ ГРОМЧЕ...")

            time.sleep(0.05)


def coop_interface():
    """Интерфейс кооперативного режима"""
    st.subheader("👥 Кооперативный режим")

    role = st.radio(
        "Выберите вашу роль:",
        ["🎮 ИГРОК 1 (Получает нажатия)", "🎤 ИГРОК 2 (Кричит в микрофон)"],
        horizontal=True,
        help="Игрок 1 запускает сервер, Игрок 2 подключается к нему"
    )

    st.markdown("---")

    if "ИГРОК 1" in role:
        # ИГРОК 1 - ПОЛУЧАЕТ НАЖАТИЯ (СЕРВЕР)
        player1_interface()
    else:
        # ИГРОК 2 - КРИЧИТ В МИКРОФОН (КЛИЕНТ)
        player2_interface()


def player1_interface():
    """Интерфейс Игрока 1 (сервер, получает нажатия)"""
    st.header("🎮 Игрок 1 (Получает нажатия)")

    # Получаем локальный IP
    local_ip = st.session_state.server.get_local_ip()

    # Информация о сервере
    st.markdown(f"""
    <div class="server-info">
        <h4>🌐 Информация для подключения</h4>
        <p><strong>Ваш IP адрес:</strong> <code>{local_ip}</code></p>
        <p><strong>Порт:</strong> <code>{PORT}</code></p>
        <p><strong>Сообщите эти данные Игроку 2</strong></p>
    </div>
    """, unsafe_allow_html=True)

    # Статус сервера
    col_status, col_refresh = st.columns([3, 1])

    with col_status:
        if st.session_state.server.is_running:
            connected_clients = len(st.session_state.server.get_connected_clients())
            if connected_clients > 0:
                st.markdown(f"""
                <div class="status-box connected">
                    <h3>✅ СЕРВЕР ЗАПУЩЕН</h3>
                    <p><strong>Подключено клиентов:</strong> {connected_clients}</p>
                    <p><strong>Статус:</strong> Готов получать команды</p>
                </div>
                """, unsafe_allow_html=True)
            else:
                st.markdown(f"""
                <div class="status-box waiting">
                    <h3>🔄 СЕРВЕР ЗАПУЩЕН</h3>
                    <p><strong>Ожидание подключения Игрока 2...</strong></p>
                    <p>Игрок 2 должен ввести ваш IP: <code>{local_ip}</code></p>
                </div>
                """, unsafe_allow_html=True)
        else:
            st.markdown("""
            <div class="status-box disconnected">
                <h3>⏸️ СЕРВЕР ОСТАНОВЛЕН</h3>
                <p><strong>Для начала работы нажмите "ЗАПУСТИТЬ СЕРВЕР"</strong></p>
            </div>
            """, unsafe_allow_html=True)

    with col_refresh:
        if st.button("🔄 Обновить", use_container_width=True, type="secondary"):
            st.session_state.server.refresh_connection()
            st.rerun()

    # Управление сервером
    col_start, col_stop = st.columns(2)

    with col_start:
        if st.button("🌐 ЗАПУСТИТЬ СЕРВЕР", type="primary", use_container_width=True,
                     disabled=st.session_state.server.is_running):
            if st.session_state.server.start_server():
                st.success("✅ Сервер запущен!")
                time.sleep(0.5)
                st.rerun()

    with col_stop:
        if st.button("⏹️ ОСТАНОВИТЬ СЕРВЕР", type="secondary", use_container_width=True,
                     disabled=not st.session_state.server.is_running):
            st.session_state.server.stop_server()
            st.info("⏸️ Сервер остановлен")
            time.sleep(0.5)
            st.rerun()

    # Инструкция
    st.markdown("---")
    st.subheader("📋 Инструкция для Игрока 1")
    st.info("""
    1. **Запустите сервер** кнопкой выше
    2. **Сообщите свой IP адрес** Игроку 2
    3. **Дождитесь подключения** Игрока 2
    4. **Когда Игрок 2 крикнет** - у вас нажмутся клавиши
    5. **Для остановки** нажмите "ОСТАНОВИТЬ СЕРВЕР"
    """)

    # Мониторинг активности
    if st.session_state.server.is_running:
        st.markdown("---")
        st.subheader("📊 Активность сервера")

        activity_display = st.empty()
        max_checks = 100  # Ограничиваем количество проверок
        
        for i in range(max_checks):
            if not st.session_state.server.is_running:
                break
                
            connected_clients = len(st.session_state.server.get_connected_clients())

            with activity_display:
                if connected_clients > 0:
                    st.success(f"✅ Активных подключений: {connected_clients}")
                    st.info("🎮 Готов к работе! Игрок 2 может кричать в микрофон")
                else:
                    st.warning("⏳ Ожидание подключения Игрока 2...")

            time.sleep(2)


def player2_interface():
    """Интерфейс Игрока 2 (клиент, кричит в микрофон)"""
    st.header("🎤 Игрок 2 (Кричит в микрофон)")

    col1, col2 = st.columns(2)

    with col1:
        server_ip = st.text_input(
            "IP адрес Игрока 1:",
            value="localhost",
            help="Введите IP адрес который вам сообщил Игрок 1"
        )

    with col2:
        button_input = st.text_input(
            "Кнопка для нажатия:",
            value="space",
            help="Какую кнопку нажимать у Игрока 1"
        )

    # Порог громкости
    threshold = st.slider(
        "Порог срабатывания:",
        min_value=-50,
        max_value=0,
        value=-20,
        help="При какой громкости отправлять команду"
    )

    # Статус подключения
    col_status, col_connect = st.columns([3, 1])

    with col_status:
        if st.session_state.client.is_connected:
            st.markdown(f"""
            <div class="status-box connected">
                <h3>✅ ПОДКЛЮЧЕНО</h3>
                <p><strong>Сервер:</strong> {st.session_state.client.server_address}</p>
                <p><strong>Статус:</strong> Готов отправлять команды</p>
            </div>
            """, unsafe_allow_html=True)
        else:
            st.markdown("""
            <div class="status-box disconnected">
                <h3>🔌 НЕ ПОДКЛЮЧЕНО</h3>
                <p><strong>Для начала подключитесь к серверу</strong></p>
            </div>
            """, unsafe_allow_html=True)

    with col_connect:
        if st.session_state.client.is_connected:
            if st.button("🔌 ОТКЛЮЧИТЬСЯ", type="secondary", use_container_width=True):
                st.session_state.client.disconnect()
                st.session_state.processor.stop_recording()
                st.info("⏸️ Отключено от сервера")
                time.sleep(0.5)
                st.rerun()
        else:
            if st.button("🔗 ПОДКЛЮЧИТЬСЯ", type="primary", use_container_width=True):
                if st.session_state.client.connect_to_server(server_ip):
                    time.sleep(0.5)
                    st.rerun()

    # Управление микрофоном
    if st.session_state.client.is_connected:
        st.markdown("---")

        col_start, col_stop = st.columns(2)

        with col_start:
            if st.button("🎤 ЗАПУСТИТЬ МИКРОФОН", type="primary", use_container_width=True,
                         disabled=st.session_state.processor.is_recording):
                if st.session_state.processor.start_recording():
                    st.success("✅ Микрофон активирован!")
                    time.sleep(0.5)
                    st.rerun()

        with col_stop:
            if st.button("⏹️ ОСТАНОВИТЬ МИКРОФОН", type="secondary", use_container_width=True,
                         disabled=not st.session_state.processor.is_recording):
                st.session_state.processor.stop_recording()
                st.info("⏸️ Микрофон выключен")
                time.sleep(0.5)
                st.rerun()

        # Мониторинг и отправка команд
        if st.session_state.processor.is_recording:
            st.markdown("---")
            st.subheader("🎤 Мониторинг громкости")

            vol_display = st.empty()
            command_display = st.empty()

            last_send_time = 0
            max_iterations = 1000  # Защита от бесконечного цикла
            
            iteration = 0
            while (st.session_state.client.is_connected and
                   st.session_state.processor.is_recording and
                   iteration < max_iterations):
                
                iteration += 1
                audio_data = st.session_state.processor.get_audio_data()

                if audio_data is not None:
                    current_volume = calculate_volume(audio_data)

                    # Отображение громкости
                    with vol_display:
                        if current_volume > threshold:
                            st.metric("🔊 ТЕКУЩАЯ ГРОМКОСТЬ", f"{current_volume:.1f} дБ", delta="ГРОМКО")
                        else:
                            st.metric("🔈 ТЕКУЩАЯ ГРОМКОСТЬ", f"{current_volume:.1f} дБ")

                    # Проверка условия для отправки
                    current_time = time.time()

                    if current_volume > threshold and (current_time - last_send_time) > 0.5:
                        with command_display:
                            st.warning("⚡ ОТПРАВЛЯЮ КОМАНДУ...")

                        try:
                            # Формируем команду для отправки
                            if '+' in button_input:
                                keys = [k.strip() for k in button_input.split('+')]
                                key_data = {
                                    'type': 'hotkey',
                                    'keys': keys,
                                    'timestamp': time.time()
                                }
                            else:
                                key_data = {
                                    'type': 'key_press',
                                    'key': button_input,
                                    'timestamp': time.time()
                                }

                            # Отправляем команду
                            if st.session_state.client.send_key_press(key_data):
                                last_send_time = current_time

                                with command_display:
                                    if 'keys' in key_data:
                                        st.success(f"✅ Отправлено: {'+'.join(key_data['keys'])}")
                                    else:
                                        st.success(f"✅ Отправлено: {key_data['key']}")

                                time.sleep(0.3)
                            else:
                                with command_display:
                                    st.error("❌ Ошибка отправки, проверьте подключение")

                        except Exception as e:
                            with command_display:
                                st.error(f"❌ Ошибка: {str(e)[:50]}")

                    else:
                        with command_display:
                            if current_volume > threshold:
                                time_left = 0.5 - (current_time - last_send_time)
                                if time_left > 0:
                                    st.info(f"⏳ Жду {time_left:.1f} сек")
                                else:
                                    st.info("🔔 ГОТОВ К ОТПРАВКЕ")
                            else:
                                st.info("🔈 КРИЧИТЕ ГРОМЧЕ...")

                time.sleep(0.05)

        else:
            # Инструкция когда подключены но микрофон выключен
            st.markdown("---")
            st.info("""
            ### 🎤 Готов к работе!

            **Чтобы начать:**
            1. Нажмите "ЗАПУСТИТЬ МИКРОФОН"
            2. Кричите в микрофон
            3. Когда громкость превысит порог - отправится команда
            4. У Игрока 1 нажмется указанная кнопка
            """)


if __name__ == "__main__":
    main()
