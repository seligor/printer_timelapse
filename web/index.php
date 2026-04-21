<?php
// Базовая директория с таймлапсами
$baseDir = 'timelapse';

// Функция для получения всех поддиректорий принтеров
function getPrinterDirs($baseDir) {
    $printerDirs = [];

    if (!is_dir($baseDir)) {
        return $printerDirs;
    }

    $items = scandir($baseDir);
    foreach ($items as $item) {
        if ($item === '.' || $item === '..') continue;

        $fullPath = $baseDir . '/' . $item;
        if (is_dir($fullPath) && preg_match('/^printer_\d+$/', $item)) {
            $printerDirs[] = $fullPath;
        }
    }

    return $printerDirs;
}

// Функция для получения данных из JSON
function getMetadata($jsonPath) {
    if (!file_exists($jsonPath)) {
        return null;
    }

    $content = file_get_contents($jsonPath);
    if ($content === false) {
        return null;
    }

    $metadata = json_decode($content, true);
    if (json_last_error() !== JSON_ERROR_NONE) {
        return null;
    }

    return $metadata;
}

// Функция для форматирования даты
function formatDate($dateString) {
    if (!$dateString) {
        return 'Дата неизвестна';
    }

    $timestamp = strtotime($dateString);
    if ($timestamp === false) {
        return $dateString;
    }

    return date('d.m.Y H:i:s', $timestamp);
}

// Функция для вычисления длительности печати
function calculateDuration($frameCount, $captureInterval) {
    if (!$frameCount || !$captureInterval || $frameCount <= 0 || $captureInterval <= 0) {
        return null;
    }

    $seconds = $frameCount * $captureInterval;
    $hours = floor($seconds / 3600);
    $minutes = floor(($seconds % 3600) / 60);
    $secs = $seconds % 60;

    return sprintf("%02d:%02d:%02d", $hours, $minutes, $secs);
}

// Функция для получения имени принтера
function getPrinterName($printerId) {
    $names = [
        'printer_1' => 'Printer 1',
        'printer_2' => 'Printer 2',
        'printer_3' => 'Printer 3',
        'printer_4' => 'Printer 4',
        'printer_5' => 'Printer 5',
        'printer_6' => 'Printer 6',
    ];

    return $names[$printerId] ?? ucfirst(str_replace('_', ' ', $printerId));
}

// Функция для получения цвета принтера
function getPrinterColor($printerId) {
    $colors = [
        'printer_1' => '#4CAF50',
        'printer_2' => '#2196F3',
        'printer_3' => '#FF9800',
        'printer_4' => '#9C27B0',
        'printer_5' => '#F44336',
        'printer_6' => '#00BCD4',
    ];

    return $colors[$printerId] ?? '#888';
}

try {
    $printerDirs = getPrinterDirs($baseDir);

    if (empty($printerDirs)) {
        throw new Exception("Не найдено ни одной директории с таймлапсами");
    }

    $fileList = [];
    $printersStats = [];

    foreach ($printerDirs as $printerDir) {
        $printerId = basename($printerDir);

        $files = scandir($printerDir);
        $files = array_diff($files, array('.', '..'));

        $printerVideoCount = 0;

        foreach ($files as $file) {
            if (pathinfo($file, PATHINFO_EXTENSION) !== 'mp4') {
                continue;
            }

            $filePath = $printerDir . '/' . $file;
            $jsonPath = $printerDir . '/' . pathinfo($file, PATHINFO_FILENAME) . '.json';
            $thumbnailPath = $printerDir . '/' . pathinfo($file, PATHINFO_FILENAME) . '.jpg';

            $metadata = getMetadata($jsonPath);

            if (!file_exists($thumbnailPath)) {
                $thumbnailPath = 'placeholder.jpg';
            }

            $frameCount = $metadata['frame_count'] ?? null;
            $captureInterval = $metadata['capture_interval'] ?? null;
            $endTime = $metadata['end_time'] ?? null;
            $modelName = $metadata['filename'] ?? pathinfo($file, PATHINFO_FILENAME);

            $modelName = str_replace('.gcode', '', $modelName);
            $modelName = str_replace('_', ' ', $modelName);

            $duration = calculateDuration($frameCount, $captureInterval);

            if ($endTime) {
                $completionDate = formatDate($endTime);
                $timestamp = strtotime($endTime);
            } else {
                $completionDate = date('d.m.Y H:i:s', filemtime($filePath));
                $timestamp = filemtime($filePath);
            }

            $fileList[] = [
                'path' => $filePath,
                'thumbnail' => $thumbnailPath,
                'printer_id' => $printerId,
                'printer_name' => getPrinterName($printerId),
                'printer_color' => getPrinterColor($printerId),
                'model_name' => $modelName,
                'completion_date' => $completionDate,
                'timestamp' => $timestamp,
                'duration' => $duration
            ];

            $printerVideoCount++;
        }

        if ($printerVideoCount > 0) {
            $printersStats[$printerId] = [
                'name' => getPrinterName($printerId),
                'color' => getPrinterColor($printerId),
                'count' => $printerVideoCount
            ];
        }
    }

    usort($fileList, function($a, $b) {
        return $b['timestamp'] - $a['timestamp'];
    });

} catch (Exception $e) {
    error_log("Ошибка: " . $e->getMessage());
    die("Произошла ошибка при обработке видео");
}
?>

<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Таймлапсы 3D принтеров</title>
    <link rel="stylesheet" href="styles.css">
</head>
<body>
    <div class="container">
        <h1>Таймлапсы 3D печати</h1>

        <?php if (empty($fileList)): ?>
            <div class="empty-state">
                <p>Пока нет ни одного таймлапса</p>
                <p>Начните печать на принтере, и видео появится здесь автоматически</p>
            </div>
        <?php else: ?>
            <!-- Статистика по принтерам -->
            <div class="printers-stats">
                <?php foreach ($printersStats as $printerId => $stats): ?>
                    <div class="printer-stat" style="border-left-color: <?php echo $stats['color']; ?>">
                        <span class="printer-stat-name"><?php echo htmlspecialchars($stats['name']); ?></span>
                        <span class="printer-stat-count"><?php echo $stats['count']; ?></span>
                    </div>
                <?php endforeach; ?>
            </div>

            <!-- Фильтр по принтерам -->
            <div class="filter-bar">
                <button class="filter-btn active" data-filter="all">Все</button>
                <?php foreach ($printersStats as $printerId => $stats): ?>
                    <button class="filter-btn" data-filter="<?php echo $printerId; ?>">
                        <?php echo htmlspecialchars($stats['name']); ?>
                    </button>
                <?php endforeach; ?>
            </div>

            <!-- Сетка видео -->
            <div class="video-grid" id="videoGrid">
                <?php foreach ($fileList as $file): ?>
                    <div class="video-card" data-printer="<?php echo $file['printer_id']; ?>">
                        <div class="video-thumbnail">
                            <a href="<?php echo $file['path']; ?>" target="_blank">
                                <img src="<?php echo $file['thumbnail']; ?>" alt="Превью" loading="lazy">
                                <div class="play-overlay"></div>
                            </a>
                        </div>
                        <div class="video-info">
                            <div class="video-title">
                                <span class="printer-badge" style="background-color: <?php echo $file['printer_color']; ?>">
                                    <?php echo htmlspecialchars($file['printer_name']); ?>
                                </span>
                                <span class="model-name"><?php echo htmlspecialchars($file['model_name']); ?></span>
                            </div>
                            <div class="video-meta">
                                <div class="meta-item">
                                    <span class="meta-label">Завершена:</span>
                                    <span class="meta-value"><?php echo $file['completion_date']; ?></span>
                                </div>
                                <?php if ($file['duration']): ?>
                                <div class="meta-item">
                                    <span class="meta-label">Длительность:</span>
                                    <span class="meta-value"><?php echo $file['duration']; ?></span>
                                </div>
                                <?php endif; ?>
                            </div>
                            <div class="video-actions">
                                <a href="<?php echo $file['path']; ?>" class="btn btn-play" target="_blank">Смотреть</a>
                                <a href="<?php echo $file['path']; ?>" class="btn btn-download" download>Скачать</a>
                            </div>
                        </div>
                    </div>
                <?php endforeach; ?>
            </div>
        <?php endif; ?>
    </div>

    <script>
        document.addEventListener('DOMContentLoaded', function() {
            const filterBtns = document.querySelectorAll('.filter-btn');
            const videoCards = document.querySelectorAll('.video-card');

            filterBtns.forEach(btn => {
                btn.addEventListener('click', function() {
                    filterBtns.forEach(b => b.classList.remove('active'));
                    this.classList.add('active');

                    const filterValue = this.getAttribute('data-filter');

                    videoCards.forEach(card => {
                        if (filterValue === 'all') {
                            card.style.display = '';
                        } else {
                            const printerId = card.getAttribute('data-printer');
                            card.style.display = printerId === filterValue ? '' : 'none';
                        }
                    });
                });
            });
        });
    </script>
</body>
</html>
