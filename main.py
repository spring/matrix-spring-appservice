import asyncio
import logging.config
import sys
import copy
import yaml
import xmlrpc.client

from typing import Dict, List, Match, Optional, Set, Tuple, TYPE_CHECKING
from urllib.parse import quote

from matrix_client.api import MatrixHttpApi

from mautrix_appservice import AppService
from m_types import MatrixEvent, MatrixEventID, MatrixRoomID, MatrixUserID

from asyncspring import spring

with open("config.yaml", 'r') as yml_file:
    config = yaml.load(yml_file)

logging.config.dictConfig(copy.deepcopy(config["logging"]))
log = logging.getLogger("matrix-spring.init")  # type: logging.Logger
log.debug(f"Initializing matrix-spring")

loop = asyncio.get_event_loop()  # type: asyncio.AbstractEventLoop

state_store = "state_store.json"

mebibyte = 1024 ** 2

matrix_api = MatrixHttpApi(config["homeserver"]["address"])

appserv = AppService(config["homeserver"]["address"], config["homeserver"]["domain"],
                     config["appservice"]["as_token"], config["appservice"]["hs_token"],
                     config["appservice"]["bot_username"], log="spring_as", loop=loop,
                     verify_ssl=config["homeserver"]["verify_ssl"], state_store=state_store,
                     real_user_content_key="net.maunium.telegram.puppet",
                     aiohttp_params={"client_max_size": config["appservice"]["max_body_size"] * mebibyte
                                     })

DOMAINS = ["[matrix]", "[jauriarts]"]


def get_matrix_room_id(room):
    room_id = matrix_api.get_room_id(room)
    return room_id


async def get_matrix_room_alias(room):
    room_alias = await appserv.intent.client.request(
        "GET",
        f"/rooms/{quote(room, safe='')}/state/m.room.aliases/{config['homeserver']['domain']}")

    return room_alias


def remove_matrix_room(room):
    matrix_api.remove_room_alias(f"#spring_{room}:{config['homeserver']['domain']}")


async def get_users_in_matrix_rooms():
    rooms = await appserv.intent.get_joined_rooms()
    log.debug(rooms)
    spring_users_in_room = dict()

    for room in rooms:
        matrix_users = await appserv.intent.get_room_members(room)
        log.debug(matrix_users)
        for user in matrix_users:
            if not user.startswith("@spring"):
                log.debug(user)
                spring_users_in_room[user] = room

    return spring_users_in_room


class SpringAppService(object):

    def __init__(self):

        # await appserv.intent.add_room_alias(room_id="!VDtYyDdWFgqjyYVhpZ:jauriarts.org", localpart="spring_main"))

        self.spring_clients = dict()

        self.bot = None

    async def run(self):

        self.bot = await spring.connect(config["spring"]["address"],
                                        port=config["spring"]["port"],
                                        use_ssl=config["spring"]["ssl"],
                                        name="appservice")

        self.bot.channels_to_join.append("#test")
        self.bot.channels_to_join.append("#moddev")
        self.bot.channels_to_join.append("#sy")
        self.bot.channels_to_join.append("#s44")
        self.bot.channels_to_join.append("#springlobby")

        self.bot.login(config["spring"]["bot_username"],
                       config["spring"]["bot_password"])

    async def leave_all_matrix_rooms(self, username):
        user = appserv.intent.user(username)
        for room in await user.get_joined_rooms():
            await  user.leave_room(room)

    async def login_matrix_account(self, username):
        matrix_id = f"@spring_{username.lower()}:{config['homeserver']['domain']}"
        user = appserv.intent.user(matrix_id)

        task = [user.set_presence("online"),
                user.set_display_name(f"{username} (Lobby)")]

        loop.run_until_complete(asyncio.gather(*task, loop=loop))

    async def logout_matrix_account(self, username):
        matrix_id = f"@spring_{username.lower()}:{config['homeserver']['domain']}"
        user = appserv.intent.user(matrix_id)

        rooms = await user.get_joined_rooms()

        for room_id in rooms:
            await user.leave_room(room_id=room_id)

        task = [user.set_presence("offline")]

        loop.run_until_complete(asyncio.gather(*task, loop=loop))

    async def join_matrix_room(self, room, clients):
        room_alias = f"#spring_{room.lower()}:{config['homeserver']['domain']}"

        for client in clients:
            if client != "appservice":
                if not any(domain in client for domain in DOMAINS):
                    matrix_id = f"@spring_{client.lower()}:{config['homeserver']['domain']}"
                    user = appserv.intent.user(matrix_id)

                    await user.join_room(room_alias)

    async def leave_matrix_room(self, room, clients):
        for client in clients:
            if client != "spring":

                matrix_id = f"@spring_{client}:{config['homeserver']['domain']}"
                room_alias = f"#spring_{room}:{config['homeserver']['domain']}"

                user = appserv.intent.user(matrix_id)
                room_id = get_matrix_room_id(room_alias)

                await user.leave_room(room_id=room_id)

    async def create_matrix_room(self, room):
        room_alias = f"#spring_{room}:{config['homeserver']['domain']}"
        try:
            room_id = await appserv.intent.create_room(alias=room_alias, is_public=True)
            await appserv.intent.join_room(room_id)
            log.debug(f"room created = {room_id}")
        except Exception as e:
            log.debug(e)

    async def said(self, user, room, message):
        matrix_id = f"@spring_{user.lower()}:{config['homeserver']['domain']}"
        room_alias = f"#spring_{room}:{config['homeserver']['domain']}"

        if matrix_id == "@spring_glenda:jaurarts.org":
            return

        room_id = get_matrix_room_id(room_alias)
        user = appserv.intent.user(matrix_id)

        await user.send_text(room_id, message)

    async def connect_matrix_users_to_spring(self, username, room):
        room_id = get_matrix_room_id(room)
        display_name = await appserv.intent.get_displayname(user_id=username, room_id=room_id)

        domain = username.split(":")[1].split(".")[0]
        spring_username = "[{1}]{0}".format(display_name, domain)

        self.spring_clients[spring_username] = SpringClient(spring_username, config["spring"]["fake_user_pass"], ["test"])
        await self.spring_clients[spring_username].connect()
        self.spring_clients[spring_username].login()

    def register(self, spring_username):
        self.spring_clients[spring_username].register()

    def accept_agreement(self, spring_username):
        self.spring_clients[spring_username].accept()


class SpringClient(object):

    def __init__(self, username, password, rooms):
        self.username = username
        self.password = password
        self.rooms = rooms

        self.bot = None

    async def connect(self):
        self.bot = await spring.connect(config["spring"]["address"],
                                        port=config["spring"]["port"],
                                        use_ssl=config["spring"]["ssl"],
                                        name=self.username)

    def register(self):
        self.bot.register(self.username, self.password, "turboss@mail.com")

    def login(self):
        self.bot.login(self.username, self.password)

    async def join(self, room):
        print(room)

    def accept(self):
        self.bot.accept()


async def init_spring_users(spring_appserv):

    members = dict()

    rooms = await appserv.intent.get_joined_rooms()
    for room_id in rooms:
        room_alias = await get_matrix_room_alias(room_id)
        members[room_alias['aliases'][0]] = await appserv.intent.get_room_members(room_id=room_id)

    for room, member_list in members.items():
        for member in member_list:
            if member.startswith("@id_"):
                with xmlrpc.client.ServerProxy("http://localhost:8300/") as proxy:
                    print(member)
                    status = proxy.get_account_info(member)

                    print(status)

            if not member.startswith("@spring"):
                await spring_appserv.connect_matrix_users_to_spring(member, room)


def main():

    with appserv.run(config["appservice"]["hostname"], config["appservice"]["port"]) as start:

        ################
        #
        # Initialization
        #
        ################

        log.info("Initialization complete, running startup actions")

        admin_list = config["appservice"]["admins"]
        admin_room = config["appservice"]["admin_room"]

        spring_appservice = SpringAppService()

        tasks = (spring_appservice.run(), start)
        loop.run_until_complete(asyncio.gather(*tasks, loop=loop))

        appservice_account = loop.run_until_complete(appserv.intent.whoami())
        user = appserv.intent.user(appservice_account)
        loop.run_until_complete(user.set_presence("online"))

        ################
        #
        # Matrix events
        #
        ################

        async def handle_command(body):
            cmd = body[1:].split(" ")[0]
            args = body[1:].split(" ")[1:]

            if cmd == "set_room_alias":
                if len(args) == 2:
                    await user.add_room_alias(room_id=args[0], localpart=args[1])

            elif cmd == "join_room":
                if len(args) == 1:
                    await user.join_room(room_id=args[0])

            elif cmd == "leave_room":
                if len(args) == 1:
                    await user.leave_room(room_id=args[0])


        @appserv.matrix_event_handler
        async def handle_event(event: MatrixEvent) -> None:
            log.debug(event)
            event_type = event.get("type", "m.unknown")  # type: str
            room_id = event.get("room_id", None)  # type: Optional[MatrixRoomID]
            event_id = event.get("event_id", None)  # type: Optional[MatrixEventID]
            sender = event.get("sender", None)  # type: Optional[MatrixUserID]
            content = event.get("content", {})  # type: Dict

            if sender in admin_list:
                if room_id != admin_room:
                    return
                if event_type == "m.room.message":
                    body = content.get("body")
                    if body.startswith("!"):
                        await handle_command(body)
            # else:
            #    if event_type == "m.room.message":
            #         body = content.get("body")


            """
            if event_type == "m.room.message":
                if sender.startswith("@spring"):
                    return

                print(content.get("body"))
            
            if event_type == "m.room.member":
                membership = content.get("membership")
                if membership == "join":
                    await spring_appservice.connect_matrix_users_to_spring(sender, room_id)
            """

        ################
        #
        # Spring events
        #
        ################
        
        @spring_appservice.bot.on("clients")
        async def on_lobby_clients(message):
            if message.client.name == "appservice":
                channel = message.params[0]
                clients = message.params[1:]
                await spring_appservice.join_matrix_room(channel, clients)

        @spring_appservice.bot.on("joined")
        async def on_lobby_joined(message, user, channel):
            if message.client.name == "appservice":
                await spring_appservice.join_matrix_room(channel, [user.username])

        @spring_appservice.bot.on("left")
        async def on_lobby_left(message, user, channel, reason):
            if message.client.name == "appservice":
                await spring_appservice.leave_matrix_room(channel, [user.username])

        @spring_appservice.bot.on("said")
        async def on_lobby_said(message, user, target, text):
            if user == "Glenda":
                return
            if message.client.name == "appservice":
                await spring_appservice.said(user, target, text)

        @spring_appservice.bot.on("denied")
        async def on_lobby_denied(message):
            if message.client.name != "appservice":
                user = message.client.name
                await spring_appservice.register(user)

        @spring_appservice.bot.on("adduser")
        async def on_lobby_adduser(message):
            if message.client.name == "appservice":
                username = message.params[0]

                if username == "ChanServ":
                    return
                if username == "appservice":
                    return

                await spring_appservice.login_matrix_account(username)

        @spring_appservice.bot.on("removeuser")
        async def on_lobby_removeuser(message):
            if message.client.name == "appservice":
                username = message.params[0]

                if username == "ChanServ":
                    return
                if username == "appservice":
                    return

                await spring_appservice.logout_matrix_account(username)

        @spring_appservice.bot.on("agreement_end")
        async def on_lobby_agreement_end(message):
            username = message.client.username
            print("NO OK")
            spring_appservice.accept_agreement(username)
            print("OK")

        log.info("Startup actions complete, now running forever")
        loop.run_forever()


if __name__ == "__main__":
    main()
