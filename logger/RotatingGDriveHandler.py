import os
from logging.handlers import RotatingFileHandler

import db.gapi.gdrive_manager


class RotatingGDriveHandler(RotatingFileHandler):
    def __init__(
        self,
        filename: str,
        max_bytes: int = 0,
        backup_count: int = 0,
    ):
        super().__init__(
            filename, maxBytes=max_bytes, backupCount=backup_count, encoding="utf8"
        )

    def doRollover(self):
        super().doRollover()
        gdrive_db = db.gapi.gdrive_manager.GDriveManager()
        if self.backupCount > 0:
            for i in range(self.backupCount - 1, 0, -1):
                old_name = os.path.basename(
                    self.rotation_filename("%s.%d" % (self.baseFilename, i))
                )
                new_name = os.path.basename(
                    self.rotation_filename("%s.%d" % (self.baseFilename, i + 1))
                )
                if gdrive_db.is_file_exists(new_name):
                    gdrive_db.delete_file(new_name)
                if gdrive_db.is_file_exists(old_name):
                    gdrive_db.rename_file(old_name, new_name)
            gdrive_db.upload_file(self.baseFilename + ".1")
