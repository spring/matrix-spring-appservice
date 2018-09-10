import asyncio
import logging.config
import sys
import copy
import yaml

from mautrix_appservice import AppService
from asyncspring import spring

with open("config.yaml", 'r') as yml_file:
    config = yaml.load(yml_file)

logging.config.dictConfig(copy.deepcopy(config["logging"]))
log = logging.getLogger("matrix-spring.init")  # type: logging.Logger
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


async def spring_bot():
    bot = await spring.connect(config["spring"]["address"],
                               port=config["spring"]["port"],
                               use_ssl=config["spring"]["ssl"])

    bot.login(config["spring"]["bot_username"],
              config["spring"]["bot_password"])

    bot.channels_to_join.append("#test")
    bot.channels_to_join.append("#sy")
    bot.channels_to_join.append("#moddev")

    @bot.on("join")
    def user_joined(message, source, params):
        print("lol")

    @bot.on("said")
    def user_said(message, source, params):
        print("said")


async def leave_all_rooms(username):
    user = appserv.intent.user(username)
    for room in await user.get_joined_rooms():
        await  user.leave_room(room)


async def join_room(username, room):
    user = appserv.intent.user(username)
    await user.join_room(room)
    await user.set_presence("online")
    await user.set_display_name("TurBoss (lobby)")


with appserv.run(config["appservice"]["hostname"], config["appservice"]["port"]) as start:

    try:
        log.info("Initialization complete, running startup actions")

        tasks = (spring_bot(), start)

        loop.run_until_complete(asyncio.gather(*tasks, loop=loop))

        log.info("Startup actions complete, now running forever")
        loop.run_forever()

    except KeyboardInterrupt:
        log.debug("Keyboard interrupt received, stopping clients")
        # loop.run_until_complete(asyncio.gather(*[user.stop() for user in User.by_tgid.values()], loop=loop))
        log.debug("Clients stopped, shutting down")
        sys.exit(0)
