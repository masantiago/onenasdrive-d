#!/usr/bin/python
# -*- coding: utf-8 -*-

import gc, sys
from config import *
from onedrive import api_v5
import components
import time


def start_workers():
    for i in range(NUM_OF_WORKERS):
        w = components.TaskWorker()
        w.start()

def start_scanners(api, account):
        components.API = api
        components.CONFIG_FILE = account["config_file"]

        # Reset queues
        components.EVENT_STOP.clear()
        with components.TASK_QUEUE.mutex:
            components.TASK_QUEUE.queue.clear()
        with components.SCANNER_QUEUE.mutex:
            components.SCANNER_QUEUE.queue.clear()

        components.DirScanner(account["local_path"], account["remote_path"]).start()
        components.Waiter().start()
        components.EVENT_STOP.wait(MAX_WORKER_DURATION)

def main():

    gc.enable()
    try:
        apis = [api_v5.PersistentOneDriveAPI.from_conf(account["config_file"]) for account in ACCOUNTS]
    except:
        print "Process cannot get information from the server. Exit."
        sys.exit(1)

    gc.collect()

    start_workers()
    log.info("***********************************************")

    while True:
        for i, api in enumerate(apis):
            log.info("Init scanner of account: " + ACCOUNTS[i]["name"])
            start_scanners(api, ACCOUNTS[i])
            log.info("***********************************************")

        time.sleep(PULL_INTERVAL)

if __name__ == "__main__":
    main()