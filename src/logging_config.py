import logging
import logging.config
import os

import yaml


logger = logging.getLogger(__name__)


def init_logger():
    # Load logging config file
    with open("conf/logging.yaml", "r") as f:
        raw = f.read()

    # Expand out env vars and apply config
    expanded = os.path.expandvars(raw).replace("\\", "/")
    config = yaml.safe_load(expanded)
    logging.config.dictConfig(config)

    # Find the file_handler so we can use it later
    file_handler = None
    for handler in logging.getLogger().handlers:
        if isinstance(handler, logging.FileHandler):
            file_handler = handler
            break

    # Make the logging directory if needed
    if file_handler:
        log_dir_name = os.path.dirname(file_handler.baseFilename)
        os.makedirs(log_dir_name, exist_ok=True)

    # If in debug mode, or file_handler isn't set, also log to the console
    if os.getenv("PYWALLPAPER_DEBUG_MODE") or file_handler is None:
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.DEBUG)
        # Use the same formatter as defined in the YAML
        if file_handler is None:
            formatter = logging.Formatter("[%(asctime)s] %(levelname)s in %(name)s: %(message)s")
        else:
            formatter = file_handler.formatter
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)

    logger.info("Logger initialized")
    if file_handler is None:
        logger.warning("No file handler is configured. Logging to the console.")
