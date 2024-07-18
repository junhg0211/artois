import unicodedata
from datetime import datetime, timedelta
from difflib import SequenceMatcher
from time import sleep


def normalise(string: str):
    return ''.join(c for c in unicodedata.normalize('NFD', string) if unicodedata.category(c) != 'Mn').lower()


def generate_dictionary_url(spreadsheet_id: str) -> str:
    return f'https://docs.google.com/spreadsheets/d/{spreadsheet_id}'


def similarity(a, b) -> float:
    return SequenceMatcher(None, a, b).ratio()


last_wait = datetime.now()

def wait(seconds):
    global last_wait

    while last_wait + timedelta(seconds=seconds) > datetime.now():
        sleep(0.1)
    last_wait = datetime.now()