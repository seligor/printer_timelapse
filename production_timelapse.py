#!/usr/bin/env python3
import asyncio
import aiohttp
import aiofiles
import json
import subprocess
import shutil
from pathlib import Path
from datetime import datetime
import logging
from typing import Optional, Dict, Any

class ProductionTimelapse:
    def __init__(self, printer_id: str, printer_ip: str, config: Dict[str, Any]):
        self.printer_id = printer_id
        self.printer_ip = printer_ip
        self.capture_interval = config.get('capture_interval', 5)
        self.frames_per_second = config.get('frames_per_second', 10)
        self.delete_frames_after_render = config.get('delete_frames_after_render', True)

        # Параметры режимов
        self.detect_first_layer = config.get('detect_first_layer', False)
        self.layer_mode = config.get('layer_mode', False)
        self.min_layer_interval = config.get('min_layer_interval', 2)
        self.max_wait_for_first_layer = config.get('max_wait_for_first_layer', 600)

        # Валидация: если layer_mode включён, но detect_first_layer выключен
        if self.layer_mode and not self.detect_first_layer:
            self.logger.warning("layer_mode requires detect_first_layer. Enabling detect_first_layer automatically")
            self.detect_first_layer = True

        # Директории
        self.frames_base_dir = Path(config.get('frames_base_dir', './timelapses/frames'))
        self.video_base_dir = Path(config.get('video_base_dir', './timelapses/videos'))
        self.thumbnail_base_dir = Path(config.get('thumbnail_base_dir', './timelapses/thumbnails'))

        # Создаём директории для конкретного принтера
        self.frames_dir = self.frames_base_dir
        self.video_dir = self.video_base_dir
        self.thumbnail_dir = self.thumbnail_base_dir

        self.frames_dir.mkdir(parents=True, exist_ok=True)
        self.video_dir.mkdir(parents=True, exist_ok=True)
        self.thumbnail_dir.mkdir(parents=True, exist_ok=True)

        # Состояние
        self.is_capturing = False
        self.current_print: Optional[Dict] = None
        self.capture_task: Optional[asyncio.Task] = None
        self.last_layer = -1
        self.last_capture_time = 0

        # Настройка логирования
        self.logger = logging.getLogger(f"Printer_{printer_id}")

        # Логируем режим работы
        mode_parts = []
        if self.detect_first_layer:
            mode_parts.append("detect first layer")
        if self.layer_mode:
            mode_parts.append("layer mode (capture on layer change)")
        else:
            mode_parts.append(f"time mode (every {self.capture_interval}s)")

        self.logger.info(f"Initialized with: {', '.join(mode_parts)}")

    async def get_status(self) -> tuple:
        """Получить статус печати"""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"http://{self.printer_ip}:7125/printer/objects/query?print_stats",
                    timeout=aiohttp.ClientTimeout(total=3)
                ) as response:
                    if response.status == 200:
                        data = await response.json()
                        status = data.get('result', {}).get('status', {}).get('print_stats', {})
                        return status.get('state'), status.get('filename')
        except Exception as e:
            self.logger.debug(f"Status check failed: {e}")
        return None, None

    async def get_current_layer(self) -> int:
        """Получить текущий слой из Moonraker"""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"http://{self.printer_ip}:7125/printer/objects/query?print_stats",
                    timeout=aiohttp.ClientTimeout(total=3)
                ) as response:
                    if response.status == 200:
                        data = await response.json()
                        current_layer = data.get('result', {}).get('status', {}).get('print_stats', {}).get('info', {}).get('current_layer')
                        if current_layer is not None:
                            return int(current_layer)
        except Exception as e:
            self.logger.debug(f"Failed to get current layer: {e}")
        return -1

    async def wait_for_first_layer(self) -> bool:
        """Ожидает появления первого слоя (только по current_layer)"""
        if not self.detect_first_layer:
            return True

        self.logger.info(f"Waiting for first layer...")
        start_wait = datetime.now()

        while (datetime.now() - start_wait).seconds < self.max_wait_for_first_layer:
            current_layer = await self.get_current_layer()

            if current_layer >= 0:
                self.logger.info(f"First layer detected (layer {current_layer})")
                return True

            await asyncio.sleep(1)

        self.logger.warning(f"Timeout waiting for first layer after {self.max_wait_for_first_layer}s, starting capture anyway")
        return True

    async def should_capture_layer_mode(self) -> bool:
        """Проверяет, нужно ли делать снимок в режиме по слоям"""
        current_layer = await self.get_current_layer()

        # Если слой не изменился или не определён — не снимаем
        if current_layer == -1 or current_layer == self.last_layer:
            return False

        # Если слой изменился
        if current_layer != self.last_layer:
            # Проверяем минимальный интервал между снимками
            current_time = asyncio.get_event_loop().time()
            if current_time - self.last_capture_time >= self.min_layer_interval:
                self.last_layer = current_layer
                self.last_capture_time = current_time
                self.logger.debug(f"Layer changed to {current_layer}, capturing")
                return True
            else:
                self.logger.debug(f"Layer changed to {current_layer} but min interval not met")

        return False

    async def take_snapshot(self, output_path: Path) -> bool:
        """Сделать снимок"""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"http://{self.printer_ip}/webcam/?action=snapshot",
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as response:
                    if response.status == 200:
                        content = await response.read()
                        if len(content) > 1000:
                            async with aiofiles.open(output_path, 'wb') as f:
                                await f.write(content)
                            return True
        except Exception as e:
            self.logger.error(f"Snapshot error: {e}")
        return False

    def generate_unique_filename(self, filename: str, timestamp: datetime) -> str:
        """Генерирует уникальное имя файла на основе имени модели и времени"""
        model_name = Path(filename).stem.replace(' ', '_')
        time_str = timestamp.strftime("%Y-%m-%d_%H-%M")
        return f"{model_name}_{time_str}"

    async def capture_loop_layer_mode(self):
        """Цикл захвата в режиме по слоям"""
        frame = 1
        self.logger.info("Starting capture loop in LAYER mode (capture on each layer change)")
        self.last_layer = -1
        self.last_capture_time = 0

        while self.is_capturing and self.current_print:
            if await self.should_capture_layer_mode():
                frame_path = self.current_print['frames_dir'] / f"frame_{frame:04d}.jpg"
                success = await self.take_snapshot(frame_path)

                if success:
                    self.current_print['frame_count'] += 1
                    self.logger.info(f"Captured frame {frame} (layer {self.last_layer})")
                    frame += 1
                else:
                    self.logger.error(f"Failed to capture frame {frame}")

            await asyncio.sleep(1)

    async def capture_loop_time_mode(self):
        """Цикл захвата в режиме по времени"""
        frame = 1
        self.logger.info(f"Starting capture loop in TIME mode (interval: {self.capture_interval}s)")

        while self.is_capturing and self.current_print:
            frame_path = self.current_print['frames_dir'] / f"frame_{frame:04d}.jpg"
            success = await self.take_snapshot(frame_path)

            if success:
                self.current_print['frame_count'] += 1
                if frame % 10 == 0:
                    self.logger.info(f"Captured {frame} frames")
                frame += 1
            else:
                self.logger.error(f"Failed to capture frame {frame}")

            await asyncio.sleep(self.capture_interval)

    async def capture_loop(self):
        """Цикл захвата кадров (выбор режима)"""
        if self.layer_mode:
            await self.capture_loop_layer_mode()
        else:
            await self.capture_loop_time_mode()

    async def render_timelapse(self, frames_dir: Path, output_path: Path) -> bool:
        """Собрать видео из кадров"""
        frame_files = sorted(frames_dir.glob("frame_*.jpg"))
        if len(frame_files) < 2:
            self.logger.warning(f"Not enough frames: {len(frame_files)}")
            return False

        cmd = [
            'ffmpeg', '-y',
            '-framerate', str(self.frames_per_second),
            '-pattern_type', 'glob',
            '-i', str(frames_dir / 'frame_*.jpg'),
            '-c:v', 'libx264',
            '-preset', 'fast',
            '-pix_fmt', 'yuv420p',
            str(output_path)
        ]

        try:
            result = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await result.communicate()

            if result.returncode == 0:
                self.logger.info(f"Timelapse created: {output_path}")
                return True
            else:
                self.logger.error(f"FFmpeg error: {stderr.decode()}")
                return False
        except Exception as e:
            self.logger.error(f"Failed to render: {e}")
            return False

    async def create_thumbnail_from_frame(self, source_frame: Path, thumbnail_path: Path) -> bool:
        """Создать превью из существующего кадра"""
        try:
            shutil.copy2(source_frame, thumbnail_path)
            self.logger.info(f"Thumbnail created: {thumbnail_path}")
            return True
        except Exception as e:
            self.logger.error(f"Failed to create thumbnail: {e}")
            return False

    async def start_capture(self, filename: str):
        """Начать захват"""
        # Ждём реального начала печати (первого слоя), если включено
        if self.detect_first_layer:
            await self.wait_for_first_layer()

        timestamp = datetime.now()
        unique_name = self.generate_unique_filename(filename, timestamp)

        # Директории для текущей печати
        print_frames_dir = self.frames_dir / unique_name
        print_frames_dir.mkdir(parents=True, exist_ok=True)

        self.current_print = {
            'filename': filename,
            'unique_name': unique_name,
            'start_time': timestamp,
            'frame_count': 0,
            'frames_dir': print_frames_dir,
            'video_path': self.video_dir / f"{unique_name}.mp4",
            'thumbnail_path': self.thumbnail_dir / f"{unique_name}.jpg",
            'metadata_path': self.video_dir / f"{unique_name}.json",
            'detect_first_layer': self.detect_first_layer,
            'layer_mode': self.layer_mode
        }

        self.is_capturing = True
        self.capture_task = asyncio.create_task(self.capture_loop())

        # Логируем режимы
        mode_desc = []
        if self.detect_first_layer:
            mode_desc.append("first layer detection ON")
        if self.layer_mode:
            mode_desc.append("layer mode (capture on layer change)")
        else:
            mode_desc.append(f"time mode ({self.capture_interval}s interval)")

        self.logger.info(f"Started capturing: {filename}")
        self.logger.info(f"  Settings: {', '.join(mode_desc)}")
        self.logger.info(f"  Unique name: {unique_name}")
        self.logger.info(f"  Frames: {print_frames_dir}")
        self.logger.info(f"  Video will be: {self.current_print['video_path']}")

    async def stop_capture(self):
        """Остановить захват, собрать видео и создать превью"""
        if not self.is_capturing:
            return

        self.is_capturing = False
        if self.capture_task:
            await self.capture_task

        self.logger.info(f"Stopped capturing. Total frames: {self.current_print['frame_count']}")

        # Собираем видео
        success = await self.render_timelapse(
            self.current_print['frames_dir'],
            self.current_print['video_path']
        )

        if success:
            # Создаём превью из последнего кадра
            frame_files = sorted(self.current_print['frames_dir'].glob("frame_*.jpg"))
            if frame_files:
                # Берём кадр за 10 секунд до конца (или предпоследний, если мало кадров)
                if len(frame_files) >= 3:
                    thumbnail_frame = frame_files[-3]
                    self.logger.info(f"Using frame from ~10 seconds before end for thumbnail")
                elif len(frame_files) >= 2:
                    thumbnail_frame = frame_files[-2]
                    self.logger.info(f"Using second-to-last frame for thumbnail")
                else:
                    thumbnail_frame = frame_files[-1]
                    self.logger.info(f"Using last frame for thumbnail")

                await self.create_thumbnail_from_frame(
                    thumbnail_frame,
                    self.current_print['thumbnail_path']
                )

            # Удаляем кадры, если нужно
            if self.delete_frames_after_render:
                shutil.rmtree(self.current_print['frames_dir'])
                self.logger.info(f"Deleted frames directory")

        # Сохраняем метаданные
        metadata = {
            'printer_id': self.printer_id,
            'printer_ip': self.printer_ip,
            'filename': self.current_print['filename'],
            'unique_name': self.current_print['unique_name'],
            'start_time': self.current_print['start_time'].isoformat(),
            'end_time': datetime.now().isoformat(),
            'frame_count': self.current_print['frame_count'],
            'capture_interval': self.capture_interval if not self.layer_mode else 'layer',
            'layer_mode': self.layer_mode,
            'detect_first_layer': self.detect_first_layer,
            'frames_per_second': self.frames_per_second,
            'video_path': str(self.current_print['video_path']),
            'thumbnail_path': str(self.current_print['thumbnail_path']),
            'duration_seconds': self.current_print['frame_count'] / self.frames_per_second if self.current_print['frame_count'] > 0 else 0
        }

        async with aiofiles.open(self.current_print['metadata_path'], 'w') as f:
            await f.write(json.dumps(metadata, indent=2))

        self.logger.info(f"Metadata saved: {self.current_print['metadata_path']}")
        self.logger.info(f"Video: {self.current_print['video_path']}")
        self.logger.info(f"Thumbnail: {self.current_print['thumbnail_path']}")

        self.current_print = None

    async def run(self):
        """Основной цикл мониторинга"""
        self.logger.info(f"Monitoring printer {self.printer_id} at {self.printer_ip}")

        last_state = None
        last_filename = None

        while True:
            try:
                state, filename = await self.get_status()

                # Логируем изменения
                if state != last_state or filename != last_filename:
                    self.logger.info(f"Status: {last_state} -> {state}, file={filename}")
                    last_state = state
                    last_filename = filename

                # Начало печати
                if state == "printing" and filename and not self.is_capturing:
                    await self.start_capture(filename)

                # Окончание печати
                elif state in ["complete", "cancelled", "error"] and self.is_capturing:
                    await self.stop_capture()

                    # Если печать завершилась нештатно
                    if state != "complete":
                        self.logger.warning(f"Print ended with status: {state}")

                # Пауза между проверками
                if self.is_capturing:
                    await asyncio.sleep(1)
                else:
                    await asyncio.sleep(5)

            except Exception as e:
                self.logger.error(f"Main loop error: {e}")
                await asyncio.sleep(5)


async def main():
    # Настройка логирования
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler('timelapse.log'),
            logging.StreamHandler()
        ]
    )

    # Загрузка конфигурации
    import yaml
    with open('config.yaml', 'r') as f:
        config = yaml.safe_load(f)

    # Создаём воркеров для каждого принтера из конфига
    printers = []
    for printer_id, printer_config in config['printers'].items():
        printers.append(ProductionTimelapse(
            printer_id=printer_id,
            printer_ip=printer_config['ip'],
            config=printer_config
        ))

    # Запускаем всех воркеров параллельно
    tasks = [printer.run() for printer in printers]
    await asyncio.gather(*tasks)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nStopped by user")
