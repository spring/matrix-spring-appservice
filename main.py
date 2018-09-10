from typing import Coroutine, List

import argparse
import asyncio
import logging.config
import sys
import copy
import yaml

from mautrix_appservice import AppService

with open("config.yaml", 'r') as yml_file:
    config = yaml.load(yml_file)


log = logging.getLogger("matrix.init")  # type: logging.Logger
log.debug(f"Initializing matrix-spring")

loop = asyncio.get_event_loop()  # type: asyncio.AbstractEventLoop

state_store = "state_store.json"

mebibyte = 1024 ** 2

appserv = AppService(config["homeserver"]["address"], config["homeserver"]["domain"],
                     config["appservice"]["as_token"], config["appservice"]["hs_token"],
                     config["appservice"]["bot_username"], log="mau.as", loop=loop,
                     verify_ssl=config["homeserver"]["verify_ssl"], state_store=state_store,
                     real_user_content_key="net.maunium.telegram.puppet",
                     aiohttp_params={"client_max_size": config["appservice"]["max_body_size"] * mebibyte
                     })

@appserv.matrix_event_handler
def matrix_event_handler():
    print("something")


with appserv.run(config["appservice"]["hostname"], config["appservice"]["port"]) as start:
    try:
        log.debug("Initialization complete, running startup actions")
        # loop.run_until_complete(asyncio.gather(*startup_actions, loop=loop))
        log.debug("Startup actions complete, now running forever")
        loop.run_forever()
    except KeyboardInterrupt:
        log.debug("Keyboard interrupt received, stopping clients")
        # loop.run_until_complete(asyncio.gather(*[user.stop() for user in User.by_tgid.values()], loop=loop))
        log.debug("Clients stopped, shutting down")
        sys.exit(0)
