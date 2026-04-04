import logging
from pathlib import Path

log_dir = Path(".logs")
log_dir.mkdir(exist_ok=True)

formatter = logging.Formatter('%(asctime)s - [%(levelname)s] - %(name)s - %(message)s')

def _create_logger(name: str, filename: str, level=logging.INFO) -> logging.Logger:
    logger = logging.getLogger(name)
    logger.setLevel(level)
    
    # Avoid duplicate handlers if imported multiple times
    if not logger.handlers:
        # Console handler - all logs go to console
        ch = logging.StreamHandler()
        ch.setLevel(logging.INFO)
        ch.setFormatter(formatter)
        
        # File handler - specific to this logger
        fh = logging.FileHandler(log_dir / filename, encoding='utf-8')
        fh.setLevel(level)
        fh.setFormatter(formatter)
        
        logger.addHandler(ch)
        logger.addHandler(fh)
        
    return logger

# Define specialized loggers as per requirements
general_log = _create_logger("scraper.general", "scraper.log")
network_log = _create_logger("scraper.network", "network_errors.log", logging.ERROR)
blocking_log = _create_logger("scraper.blocking", "blocking_issues.log", logging.WARNING)
parsing_log = _create_logger("scraper.parsing", "parsing_errors.log", logging.ERROR)
validation_log = _create_logger("scraper.validation", "validation_issues.log", logging.WARNING)
