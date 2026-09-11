"""Load model secrets only from an explicitly configured file or process environment."""
import os
from pathlib import Path


def load_model_environment():
    # Upstream calls load_dotenv() without a path. Disable discovery in parent
    # workspaces; explicit values below do not use load_dotenv's global switch.
    os.environ['PYTHON_DOTENV_DISABLED']='1'
    path=os.environ.get('EB_PILOT_ENV_FILE')
    if not path:
        return
    file=Path(path).expanduser()
    if not file.is_file():
        raise ValueError('Configured model environment file is missing')
    from dotenv import dotenv_values
    for key,value in dotenv_values(file,interpolate=False).items():
        if value is not None and (key.startswith('LLM_') or key=='USE_LLM'):
            os.environ.setdefault(key,value)
