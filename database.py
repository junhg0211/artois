import re
from datetime import datetime
from typing import Optional

import gspread

from util import normalise, similarity, wait


class Database:
    @staticmethod
    def is_duplicate(query: str, row: list) -> bool:
        return normalise(query) == normalise(row[0]) \
               or any(normalise(query) in re.split(r'[,;] ', normalise(row[i])) for i in range(1, len(row)))

    def __init__(self, spreadsheet_key: str, sheet_number: int = 0):
        self.spreadsheet_key = spreadsheet_key
        self.sheet_number = sheet_number

        print(f'load {spreadsheet_key}')
        wait(2)
        self.credential = gspread.service_account(filename='res/google_credentials.json')
        self.sheet = self.credential.open_by_key(self.spreadsheet_key).get_worksheet(self.sheet_number)

        self.last_reload = datetime.now()
        self.sheet_values = None
        self.header = None
        self.reload()

    def reload(self):
        self.sheet_values = self.sheet.get_all_values()
        self.last_reload = datetime.now()
        self.header = self.sheet_values[0]
        return self

    async def search_rows(
        self, query: str, word_column: int, exclude_column_indexes: Optional[list] = None,
        hidden_column_indexes: Optional[list] = None
    ) -> list:
        # init exclude column index
        if exclude_column_indexes is None:
            exclude_column_indexes = list()
        if hidden_column_indexes is None:
            hidden_column_indexes = list()

        # get similar row indexes
        perfect_match = set()
        row_indexes = list()
        for i, row in enumerate(self.sheet_values):
            # exclude first row
            if i == 0:
                continue

            # calculate similarity if row cell has `query` in it
            sim = list()
            for j, cell in enumerate(row):
                if j in exclude_column_indexes:
                    continue
                values = re.split(r', |; ', cell)
                for value in values:
                    if query.lower() in value.lower():
                        sim.append(similarity(value.lower(), query.lower()))
            if sim:
                row_indexes.append((sum(sim) / len(sim), i))
                if 1.0 in sim:
                    perfect_match.add(i)

        # sort row indexes by similarity
        row_indexes = map(lambda x: x[1], sorted(row_indexes, reverse=True, key=lambda x: x[0]))

        # parse row indexes with row data
        result = list()
        for row_index in row_indexes:
            # cut over than 25th row
            if len(result) >= 25:
                break

            row = dict()
            for i, value in enumerate(self.sheet_values[row_index]):
                if not value:
                    continue
                if i in exclude_column_indexes:
                    continue
                if i in hidden_column_indexes:
                    continue
                if i == word_column:
                    continue
                row[self.header[i]] = value
            if row:
                word = self.sheet_values[row_index][word_column]
                if row_index in perfect_match:
                    word = f'__{word}__'
                result.append((word, row))

        return result