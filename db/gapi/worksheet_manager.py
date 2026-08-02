from typing import List, Optional, Tuple

from pygsheets.worksheet import Worksheet

from logger.app_logger import logger as nmd_logger

Matrix = List[List[str]]


class WorksheetManager:
    def __init__(self, worksheet: Worksheet):
        self._ws: Worksheet = worksheet
        self._cache: Optional[Matrix] = None
        self._header_range: Tuple[int, int] = (self._ws.frozen_rows, 0)

    @staticmethod
    def _validate_row(row: List[str]) -> List[str]:
        FORMULA_SIGNS = ["=", "+"]
        new_row = ["'" + v if v and v[0] in FORMULA_SIGNS else v for v in row]
        return new_row

    def _validate_values(self, values: Matrix) -> Matrix:
        new_values = [self._validate_row(v) for v in values]
        return new_values

    def fetch(self):
        nmd_logger.info(
            "GAPI: '%s' fetching worksheet '%s'",
            self._ws.spreadsheet.title,
            self._ws.title,
        )
        self._cache = self._ws.get_all_values(
            include_tailing_empty_rows=False, include_tailing_empty=False
        )
        nmd_logger.debug("GAPI: worksheet fetched; rows=%d", len(self._cache))

    def cache(self) -> Matrix:
        if self._cache is None:
            nmd_logger.debug("GAPI: worksheet cache miss")
            self.fetch()
        return self._cache

    def bold_cells(self, end_range: tuple, to_bold: bool = True):
        nmd_logger.info(
            "GAPI: (%s/%s) %s cells through %s",
            self._ws.spreadsheet.title,
            self._ws.title,
            "bolding" if to_bold else "unbolding",
            end_range,
        )
        start_range = (1, 1)
        self._ws.apply_format(
            [[start_range, end_range]], {"textFormat": {"bold": to_bold}}
        )

    def set_header(self, header: Matrix):
        nmd_logger.info(
            "GAPI: (%s/%s) setting header rows=%d",
            self._ws.spreadsheet.title,
            self._ws.title,
            len(header),
        )
        values = self.get_all_values()
        if self._header_range[0] > 0:
            end_range = tuple(x + 1 for x in self._header_range)
            self.bold_cells(end_range, False)
            self._header_range = (0, 0)
        self._ws.frozen_rows = len(header)
        self.update_values(header + values)
        if len(header) > 0:
            self._header_range = (len(header), len(header[0]))
            self.bold_cells(self._header_range)

    def ensure_header(self, header: Matrix) -> None:
        """Create or repair a worksheet header without duplicating existing rows."""
        if not header:
            nmd_logger.debug("GAPI: empty header requires no changes")
            return

        values = self.cache()
        header_rows = len(header)
        header_columns = max(len(row) for row in header)

        if self._header_range[0] == header_rows and values[:header_rows] == header:
            nmd_logger.debug("GAPI: worksheet header already valid")
            return

        if self._header_range[0] == 0 and values[:header_rows] == header:
            nmd_logger.info("GAPI: freezing existing worksheet header")
            self._ws.frozen_rows = header_rows
            self._header_range = (header_rows, header_columns)
            self.bold_cells(self._header_range)
            return

        self.set_header(header)

    def get_all_values(self) -> Matrix:
        return self.cache()[self._header_range[0] :]

    def add_row(self, row: List[str]):
        nmd_logger.info(
            f"GAPI: ({self._ws.spreadsheet.title}/{self._ws.title}) add row with {len(row)} cells"
        )
        row_index = len(self.cache())
        row = self._validate_row(row)
        self._ws.insert_rows(row=row_index, values=row)
        self.cache().append(row)
        self.adjust_columns_width()

    def sort_table(
        self,
        column_index: int,
        sort_order: str = "DESCENDING",
    ):
        nmd_logger.info(
            "GAPI: (%s/%s) sorting by column=%d order=%s",
            self._ws.spreadsheet.title,
            self._ws.title,
            column_index,
            sort_order,
        )
        start_range = (self._header_range[0] + 1, 1)
        cache = self.cache()
        end_range = (len(cache), len(cache[0]))
        self._ws.sort_range(start_range, end_range, column_index, sort_order)
        self.fetch()

    def update_values(
        self,
        values: Matrix,
        start_range: Optional[tuple] = None,
    ):
        nmd_logger.info(
            "GAPI: (%s/%s) updating %d rows from %s",
            self._ws.spreadsheet.title,
            self._ws.title,
            len(values),
            start_range,
        )
        if not start_range:
            start_range = (self._header_range[0] + 1, 1)
        self._ws.clear(start_range, (self._ws.cols, self._ws.rows))
        values = [[]] if not values else values
        values = self._validate_values(values)
        self._ws.update_values(start_range, values, extend=True)
        self.fetch()
        self.adjust_columns_width()

    def hide_column(self, column: int):
        nmd_logger.info("GAPI: hiding worksheet column=%d", column)
        self._ws.hide_dimensions(column + 1, dimension="COLUMNS")

    def hide_worksheet(self):
        nmd_logger.info("GAPI: hiding worksheet '%s'", self._ws.title)
        self._ws.hidden = True

    def adjust_columns_width(self):
        values = self.cache()
        columns = len(values[0]) if values else 0
        nmd_logger.debug("GAPI: adjusting width for %d columns", columns)
        self._ws.adjust_column_width(1, columns)
