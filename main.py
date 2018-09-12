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



class SpringAppService(object):

    def __init__(self):
        self.rooms = dict()

    async def run(self):
        self.bot = await spring.connect(config["spring"]["address"],
                                        port=config["spring"]["port"],
                                        use_ssl=config["spring"]["ssl"])

        self.bot.channels_to_join.append("#test")
        self.bot.channels_to_join.append("#moddev")
        self.bot.channels_to_join.append("#sy")

        self.bot.login(config["spring"]["bot_username"],
                       config["spring"]["bot_password"])

        for channel in self.bot.channels_to_join:
            room = channel[1:]
            room_id = f"#spring_{room}:jauriarts.org"
            try:
                log.debug(f"Creating room = {room}")
                await spring_appservice.create_room(room)
            except Exception as e:
                log.debug(e)

    async def leave_all_rooms(self, username):
        user = appserv.intent.user(username)
        for room in await user.get_joined_rooms():
            print(room)
            await  user.leave_room(room)

    async def join_room(self, room, clients):
        room_alias = f"#spring_{room}:jauriarts.org"

        for client in clients:
            if client != "appservice":
                matrix_id = f"@spring_{client}:jauriarts.org"
                user = appserv.intent.user(matrix_id)

                task = {
                    user.join_room(room_alias),
                    user.set_presence("online"),
                    user.set_display_name(f"{client} (lobby)"),
                }
                loop.run_until_complete(asyncio.gather(*task, loop=loop))

    async def leave_room(self, room, clients):
        for client in clients:
            if client != "spring":
                matrix_id = f"@spring_{client}:jauriarts.org"
                user = appserv.intent.user(matrix_id)
                await user.set_presence("offline")

    async def create_room(self, room):
        room_alias = f"#spring_{room}:jauriarts.org"
        try:
            room_id = await appserv.intent.create_room(alias=room_alias, is_public=True)
            await appserv.intent.join_room(room_id)
            log.debug(f"room created = {room_id}")
        except Exception as e:
            log.debug(e)

    async def matrix_say(self, user, room, message):
        matrix_id = f"@spring_{user}:jauriarts.org"
        user = appserv.intent.user(matrix_id)
        await user.send_text("!ckgUuMKcgcfJHSTvDP:jauriarts.org", message)


with appserv.run(config["appservice"]["hostname"], config["appservice"]["port"]) as start:

    log.info("Initialization complete, running startup actions")

    spring_appservice = SpringAppService()

    tasks = (spring_appservice.run(),
             start)

    loop.run_until_complete(asyncio.gather(*tasks, loop=loop))

    @spring_appservice.bot.on("clients")
    async def on_lobby_clients(message):
        channel = message.params[0]
        clients = message.params[1:]

        # await spring_appservice.leave_all_rooms("@spring_appservice:jauriarts.org")

        # await spring_appservice.create_room(channel)
        await spring_appservice.join_room(channel, clients)


    @spring_appservice.bot.on("joined")
    async def on_lobby_joined(message, user, channel):
        await spring_appservice.join_room(channel, [user.username])


    @spring_appservice.bot.on("left")
    async def on_lobby_left(message, user, channel, reason):
        await spring_appservice.leave_room(channel, [user.username])


    @spring_appservice.bot.on("said")
    async def on_lobby_said(message, user, target, text):
        await spring_appservice.matrix_say(user, target, text)

    log.info("Startup actions complete, now running forever")
    loop.run_forever()