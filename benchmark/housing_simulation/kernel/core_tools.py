"""Pure IDF parser shared by demo authoring; no resource-root side effects."""
import re


def parse_idf(text):
    return [[v.strip() for v in part.split(',')]
            for part in re.sub(r'!.*', '', text).split(';') if part.strip()]
