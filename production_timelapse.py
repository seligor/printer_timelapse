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

        # Настройка логирования
        self.logger = logging.getLogger(f"Printer_{printer_id}")

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
        # Убираем расширение .gcode и заменяем пробелы на подчёркивания
        model_name = Path(filename).stem.replace(' ', '_')
        # Форматируем время: 2025-05-18_21-05
        time_str = timestamp.strftime("%Y-%m-%d_%H-%M")
        # Собираем уникальное имя
        return f"{model_name}_{time_str}"

    async def capture_loop(self):
        """Цикл захвата кадров"""
        frame = 1
        while self.is_capturing and self.current_print:
            frame_path = self.current_print['frames_dir'] / f"frame_{frame:04d}.jpg"

            success = await self.take_snapshot(frame_path)
            if success:
                self.current_print['frame_count'] += 1
                if frame % 10 == 0:  # Логируем каждый 10-й кадр
                    self.logger.info(f"Captured {frame} frames")
                frame += 1
            else:
                self.logger.error(f"Failed to capture frame {frame}")

            await asyncio.sleep(self.capture_interval)

    async def render_timelapse(self, frames_dir: Path, output_path: Path) -> bool:
        """Собрать видео из кадров"""
        frame_files = sorted(frames_dir.glob("frame_*.jpg"))
        if len(frame_files) < 2:
            self.logger.warning(f"Not enough frames: {len(frame_files)}")
            return False

        # Используем ffmpeg для создания видео
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
        """Создать превью из существующего кадра (берём последний кадр)"""
        try:
            # Просто копируем последний кадр как превью
            # Можно изменить размер, если нужно
            shutil.copy2(source_frame, thumbnail_path)
            self.logger.info(f"Thumbnail created: {thumbnail_path}")
            return True
        except Exception as e:
            self.logger.error(f"Failed to create thumbnail: {e}")
            return False

    async def start_capture(self, filename: str):
        """Начать захват"""
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
            'metadata_path': self.video_dir / f"{unique_name}.json"  # JSON рядом с видео
        }

        self.is_capturing = True
        self.capture_task = asyncio.create_task(self.capture_loop())
        self.logger.info(f"  Started capturing: {filename}")
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
                last_frame = frame_files[-3]  # Берём последний кадр
                await self.create_thumbnail_from_frame(
                    last_frame,
                    self.current_print['thumbnail_path']
                )

            # Удаляем кадры, если нужно
            if self.delete_frames_after_render:
                import shutil
                shutil.rmtree(self.current_print['frames_dir'])
                self.logger.info(f"  Deleted frames directory")

        # Сохраняем метаданные
        metadata = {
            'printer_id': self.printer_id,
            'printer_ip': self.printer_ip,
            'filename': self.current_print['filename'],
            'unique_name': self.current_print['unique_name'],
            'start_time': self.current_print['start_time'].isoformat(),
            'end_time': datetime.now().isoformat(),
            'frame_count': self.current_print['frame_count'],
            'capture_interval': self.capture_interval,
            'frames_per_second': self.frames_per_second,
            'video_path': str(self.current_print['video_path']),
            'thumbnail_path': str(self.current_print['thumbnail_path']),
            'duration_seconds': self.current_print['frame_count'] / self.frames_per_second if self.current_print['frame_count'] > 0 else 0
        }

        async with aiofiles.open(self.current_print['metadata_path'], 'w') as f:
            await f.write(json.dumps(metadata, indent=2))

        self.logger.info(f"  Metadata saved: {self.current_print['metadata_path']}")
        self.logger.info(f"  Video: {self.current_print['video_path']}")
        self.logger.info(f"  Thumbnail: {self.current_print['thumbnail_path']}")

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
                    await asyncio.sleep(1)  # Во время печати проверяем чаще
                else:
                    await asyncio.sleep(5)  # В простое реже

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
