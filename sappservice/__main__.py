#!/usr/bin/env python
# -*- coding: utf-8 -*-

#   Copyright (c) 2020 TurBoss
#         <turboss@mail.com>
#
#   This file is part of Matrix Spring Appservice.
#
#   This program is free software: you can redistribute it and/or modify
#   it under the terms of the GNU General Public License as published by
#   the Free Software Foundation, either version 3 of the License, or
#   (at your option) any later version.
#
#   This program is distributed in the hope that it will be useful,
#   but WITHOUT ANY WARRANTY; without even the implied warranty of
#   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#   GNU General Public License for more details.
#
#   You should have received a copy of the GNU General Public License
#   along with this program.  If not, see <http://www.gnu.org/licenses/>.

import argparse
import asyncio
import sys

from sappservice.sappservice import sappservice

parser = argparse.ArgumentParser()
parser.add_argument('-c', '--config')
args = parser.parse_args()

config_filename = args.config
if config_filename is None:
    print("""
Matrix Spring Appservice    
Ussage: sappservice -c config.yaml
""")
    sys.exit(1)

loop = asyncio.get_event_loop()  # type: asyncio.AbstractEventLoop
loop.run_until_complete(sappservice(config_filename=config_filename, loop=loop))
loop.run_forever()
