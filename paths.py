"""Data locations; overrides are set by tools.py or environment variables."""
import os
from pathlib import Path
ROOT = Path(os.environ.get('SM_WORKSPACE', Path(__file__).parent / 'data')).resolve()
RAC = Path(os.environ.get('SM_RAC_LEVELS', ROOT / 'rac-levels')).resolve()
