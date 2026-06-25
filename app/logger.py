import logging
import os
import re
import tarfile
import zipfile
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path

from app.bot.utils.constants import LOG_GZ_ARCHIVE_FORMAT, LOG_ZIP_ARCHIVE_FORMAT
from app.config import LoggingConfig, memory_handler

LOG_DIR = "app/logs"
LOG_FILENAME = "app.log"
LOG_ENCODING = "utf-8"
LOG_ARCHIVE_SOURCE_LIMIT_MULTIPLIER = 2
ARCHIVE_NAME_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}(?:-\d+)?\.(?:zip|gz)$"
)

logger = logging.getLogger(__name__)


class ArchiveRotatingFileHandler(RotatingFileHandler):
    def __init__(
        self,
        filename,
        maxBytes=0,
        backupCount=0,
        encoding=None,
        delay=False,
        errors=None,
        archive_format=LOG_ZIP_ARCHIVE_FORMAT,
    ):
        super().__init__(
            filename=filename,
            mode="a",
            maxBytes=maxBytes,
            backupCount=backupCount,
            encoding=encoding,
            delay=delay,
            errors=errors,
        )
        if archive_format not in {LOG_ZIP_ARCHIVE_FORMAT, LOG_GZ_ARCHIVE_FORMAT}:
            raise ValueError("archive_format must be either 'zip' or 'gz'")

        self.archive_format = archive_format

    def doRollover(self) -> None:
        if self.stream:
            self.stream.close()
            self.stream = None

        if os.path.exists(self.baseFilename):
            source_size = os.path.getsize(self.baseFilename)
            archive_limit = self.maxBytes * LOG_ARCHIVE_SOURCE_LIMIT_MULTIPLIER
            if (
                self.backupCount > 0
                and source_size > 0
                and (not archive_limit or source_size <= archive_limit)
            ):
                self._archive_log_file(self._next_archive_name())
            os.remove(self.baseFilename)

        self._remove_old_archives()

        if not self.delay:
            self.stream = self._open()

    def _next_archive_name(self) -> str:
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        directory = os.path.dirname(self.baseFilename)
        archive_name = os.path.join(directory, f"{timestamp}.{self.archive_format}")
        counter = 1
        while os.path.exists(archive_name):
            archive_name = os.path.join(
                directory,
                f"{timestamp}-{counter}.{self.archive_format}",
            )
            counter += 1
        return archive_name

    def _archive_log_file(self, archive_name: str) -> None:
        if self.archive_format == LOG_ZIP_ARCHIVE_FORMAT:
            self._archive_to_zip(archive_name)
        elif self.archive_format == LOG_GZ_ARCHIVE_FORMAT:
            self._archive_to_gz(archive_name)

    def _archive_to_zip(self, archive_name: str) -> None:
        new_log_name = self._get_log_filename(archive_name)
        with zipfile.ZipFile(archive_name, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.write(filename=self.baseFilename, arcname=new_log_name)

    def _archive_to_gz(self, archive_name: str) -> None:
        new_log_name = self._get_log_filename(archive_name)
        with tarfile.open(archive_name, "w:gz") as archive:
            archive.add(name=self.baseFilename, arcname=new_log_name)

    def _get_log_filename(self, archive_name: str) -> str:
        return os.path.splitext(os.path.basename(archive_name))[0] + ".log"

    def _remove_old_archives(self) -> None:
        directory = Path(self.baseFilename).parent
        archives = sorted(
            (
                path
                for path in directory.iterdir()
                if path.is_file() and ARCHIVE_NAME_RE.match(path.name)
            ),
            key=lambda path: (path.stat().st_mtime, path.name),
        )
        archives_to_delete = (
            archives if self.backupCount <= 0 else archives[: -self.backupCount]
        )
        for archive in archives_to_delete:
            try:
                archive.unlink()
            except OSError:
                pass


def setup_logging(config: LoggingConfig) -> None:
    os.makedirs(LOG_DIR, exist_ok=True)
    log_file = os.path.join(LOG_DIR, LOG_FILENAME)

    logging.basicConfig(
        level=getattr(logging, config.LEVEL.upper(), logging.INFO),
        format=config.FORMAT,
        handlers=[
            ArchiveRotatingFileHandler(
                filename=log_file,
                encoding=LOG_ENCODING,
                archive_format=config.ARCHIVE_FORMAT,
                maxBytes=config.MAX_BYTES,
                backupCount=config.BACKUP_COUNT,
            ),
            logging.StreamHandler(),
        ],
        force=True,
    )

    for record in memory_handler.buffer:
        logger.handle(record)

    logger.debug(
        f"Logging configuration: level={config.LEVEL}, "
        f"format={config.FORMAT}, archive_format={config.ARCHIVE_FORMAT}, "
        f"max_bytes={config.MAX_BYTES}, backup_count={config.BACKUP_COUNT}"
    )

    # Suppresses logs to avoid unnecessary output
    aiogram_logger = logging.getLogger("aiogram.event")
    aiogram_logger.setLevel(logging.CRITICAL)

    aiosqlite_logger = logging.getLogger("aiosqlite")
    aiosqlite_logger.setLevel(logging.INFO)

    httpcore_logger = logging.getLogger("httpcore")
    httpcore_logger.setLevel(logging.INFO)

    aiohttp_logger = logging.getLogger("aiohttp")
    aiohttp_logger.setLevel(logging.WARNING)

    httpx_logger = logging.getLogger("httpx")
    httpx_logger.setLevel(logging.WARNING)

    urllib_logger = logging.getLogger("urllib3")
    urllib_logger.setLevel(logging.WARNING)

    apscheduler_logger = logging.getLogger("apscheduler")
    apscheduler_logger.setLevel(logging.WARNING)
