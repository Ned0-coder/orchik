import streamlit as st
import pyaudio
import numpy as np
import time
import threading
import queue
import pyautogui
import warnings

warnings.filterwarnings("ignore")

# Настройки PyAudio
CHUNK = 1024
FORMAT = pyaudio.paInt16
CHANNELS = 1
RATE = 44100


class AudioProcessor:
    def __init__(self):
        self.audio = pyaudio.PyAudio()
        self.stream = None
        self.is_recording = False
        self.audio_data = None
        self.lock = threading.Lock()

    def start_recording(self):
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
                st.error(f"Ошибка открытия микрофона: {e}")
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
            self.stream.stop_stream()
            self.stream.close()
            self.stream = None

    def cleanup(self):
        self.stop_recording()
        self.audio.terminate()


def calculate_volume(audio_data):
    """Вычисляет уровень громкости в децибелах"""
    if audio_data is None or len(audio_data) == 0:
        return -100

    try:
        # Быстрое вычисление RMS
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
        page_title="Voice Trigger App",
        page_icon="🎤",
        layout="wide"
    )

    st.title("🎤 Голосовой триггер для нажатия кнопки")
    st.markdown("---")

    # Инициализация состояния
    if 'processor' not in st.session_state:
        st.session_state.processor = AudioProcessor()
    if 'is_running' not in st.session_state:
        st.session_state.is_running = False
    if 'last_press_time' not in st.session_state:
        st.session_state.last_press_time = 0
    if 'current_volume' not in st.session_state:
        st.session_state.current_volume = -100
    if 'button_pressed' not in st.session_state:
        st.session_state.button_pressed = False

    # Основные настройки
    col1, col2, col3 = st.columns(3)

    with col1:
        st.subheader("🎯 Нажимаемая кнопка")
        button_input = st.text_input(
            "Введите кнопку:",
            value="space",
            label_visibility="collapsed",
            key="button_input"
        )
        st.caption("Примеры: space, enter, a, 1, f1, ctrl+c")

    with col2:
        st.subheader("📊 Порог громкости")
        threshold = st.slider(
            "Порог (дБ):",
            min_value=-50,
            max_value=0,
            value=-20,
            label_visibility="collapsed",
            key="threshold"
        )
        st.caption(f"Сработает при > {threshold} дБ")

    with col3:
        st.subheader("⏱️ Задержка")
        cooldown = st.slider(
            "Задержка (сек):",
            min_value=0.0,
            max_value=2.0,
            value=0.5,
            step=0.1,
            label_visibility="collapsed",
            key="cooldown"
        )
        st.caption(f"Мин. интервал: {cooldown} сек")

    st.markdown("---")

    # Кнопки управления
    col_start, col_stop, col_status = st.columns([1, 1, 2])

    with col_start:
        start_disabled = st.session_state.is_running or not button_input.strip()
        if st.button("▶️ ЗАПУСК",
                     type="primary",
                     disabled=start_disabled,
                     use_container_width=True):
            try:
                if st.session_state.processor.start_recording():
                    st.session_state.is_running = True
                    st.session_state.last_press_time = 0
                    st.session_state.button_pressed = False
                    st.success("✅ Микрофон активирован!")
                    time.sleep(0.5)
                    st.rerun()
                else:
                    st.error("❌ Не удалось запустить микрофон")
            except Exception as e:
                st.error(f"Ошибка: {e}")

    with col_stop:
        if st.button("⏹️ СТОП",
                     type="secondary",
                     disabled=not st.session_state.is_running,
                     use_container_width=True):
            st.session_state.processor.stop_recording()
            st.session_state.is_running = False
            st.info("⏸️ Микрофон выключен")
            time.sleep(0.5)
            st.rerun()

    with col_status:
        status_placeholder = st.empty()

    # Отображение тестовой информации
    test_col1, test_col2 = st.columns(2)

    with test_col1:
        test_placeholder = st.empty()

    with test_col2:
        debug_placeholder = st.empty()

    # Мониторинг громкости и нажатие клавиш
    if st.session_state.is_running:
        status_placeholder.success("🎤 МИКРОФОН АКТИВЕН - говорите громко!")

        # Создаем контейнер для отображения информации
        info_container = st.container()

        with info_container:
            vol_col1, vol_col2, vol_col3 = st.columns(3)

            with vol_col1:
                vol_display = st.empty()

            with vol_col2:
                threshold_display = st.empty()

            with vol_col3:
                trigger_display = st.empty()

        # Основной цикл мониторинга
        while st.session_state.is_running:
            try:
                # Получаем аудио данные
                audio_data = st.session_state.processor.get_audio_data()

                if audio_data is not None:
                    # Вычисляем громкость
                    current_volume = calculate_volume(audio_data)
                    st.session_state.current_volume = current_volume

                    # Обновляем отображение
                    with vol_display:
                        if current_volume > threshold:
                            st.markdown(f"### 🔊 **{current_volume:.1f} дБ**", unsafe_allow_html=True)
                        else:
                            st.markdown(f"### 🔈 {current_volume:.1f} дБ", unsafe_allow_html=True)

                    with threshold_display:
                        st.markdown(f"### 🎯 Порог: {threshold} дБ", unsafe_allow_html=True)

                    # Проверяем условие для нажатия
                    current_time = time.time()

                    # Тестовое сообщение
                    with test_placeholder:
                        st.info(f"Громкость: {current_volume:.1f} дБ | Порог: {threshold} дБ")

                    with debug_placeholder:
                        time_since_last = current_time - st.session_state.last_press_time
                        st.info(f"Время с последнего нажатия: {time_since_last:.1f} сек")

                    # Условие срабатывания
                    should_trigger = (
                            current_volume > threshold and
                            (current_time - st.session_state.last_press_time) > cooldown
                    )

                    if should_trigger:
                        with trigger_display:
                            st.warning("⚡ ТРИГГЕР СРАБОТАЛ!")

                        # Пытаемся нажать клавишу
                        try:
                            st.info(f"Пытаюсь нажать: {button_input}")

                            # Для отладки: показываем что пытаемся нажать
                            with test_placeholder:
                                st.success(f"НАЖИМАЮ КНОПКУ: {button_input}")

                            # Нажатие клавиши
                            if '+' in button_input:
                                # Комбинация клавиш
                                keys = [k.strip() for k in button_input.split('+')]
                                pyautogui.hotkey(*keys)
                            else:
                                # Одиночная клавиша
                                pyautogui.press(button_input)

                            # Обновляем время последнего нажатия
                            st.session_state.last_press_time = current_time
                            st.session_state.button_pressed = True

                            # Визуальное подтверждение
                            with trigger_display:
                                st.success(f"✅ Нажата: {button_input}")

                            # Короткая пауза чтобы увидеть сообщение
                            time.sleep(0.3)

                        except Exception as e:
                            with trigger_display:
                                st.error(f"❌ Ошибка: {str(e)}")
                            # Даже если ошибка, обновляем время чтобы не спамить
                            st.session_state.last_press_time = current_time

                    else:
                        with trigger_display:
                            if current_volume > threshold:
                                time_left = cooldown - (current_time - st.session_state.last_press_time)
                                if time_left > 0:
                                    st.info(f"⏳ Жду {time_left:.1f} сек")
                                else:
                                    st.info("🔔 ГОТОВ К НАЖАТИЮ")
                            else:
                                st.info("🔈 тихо")

                # Короткая пауза
                time.sleep(0.05)

            except Exception as e:
                st.error(f"Ошибка в цикле: {e}")
                break

    else:
        # Стартовый экран
        status_placeholder.info("⏸️ Нажмите ЗАПУСК чтобы начать")

        if st.session_state.button_pressed:
            st.success(f"✅ Последняя нажатая кнопка: {button_input}")

    # Очистка при остановке
    if not st.session_state.is_running:
        st.session_state.processor.stop_recording()


if __name__ == "__main__":
    main()
