"""Path to cognee's relational sqlite DB — shared by the cognee and local
lexical paths. Kept in its own module so neither imports the other just for
this one-liner.
"""

import os
from pathlib import Path


def cognee_db_path() -> Path:
    return Path(os.getcwd()) / ".cognee_data" / "system" / "databases" / "cognee_db"
