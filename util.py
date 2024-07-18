import unicodedata
from difflib import SequenceMatcher


def normalise(string: str):
    return ''.join(c for c in unicodedata.normalize('NFD', string) if unicodedata.category(c) != 'Mn').lower()


def generate_dictionary_url(spreadsheet_id: str) -> str:
    return f'https://docs.google.com/spreadsheets/d/{spreadsheet_id}'


def similarity(a, b) -> float:
    return SequenceMatcher(None, a, b).ratio()