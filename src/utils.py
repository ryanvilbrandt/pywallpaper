import logging
import os
import shutil
from configparser import ConfigParser
from time import perf_counter_ns

logger = logging.getLogger(__name__)
perf_list = []


def perf(title: str = ""):
    global perf_list
    if not title:
        title = "Start"
        perf_list = []
    perf_list.append((title, perf_counter_ns()))


def log_perf(title: str = "Total:"):
    logger.info("Performance times:")
    for i, perf_tuple in enumerate(perf_list):
        if i == 0:
            continue
        t1, t2 = perf_list[i - 1][1], perf_list[i][1]
        logger.info(f"  {perf_tuple[0]} {(t2 - t1) / 1_000_000:.2f} ms")
    t1, t2 = perf_list[0][1], perf_list[-1][1]
    logger.info(f"{title} {(t2 - t1) / 1_000_000:.2f} ms")


def load_config():
    c = ConfigParser()
    if not os.path.isfile("conf/config.ini"):
        shutil.copy("conf/config.ini.dist", "conf/config.ini")
    c.read("conf/config.ini")
    return c
