# Copyright (c) 2021-2022, NVIDIA CORPORATION.  All rights reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Provides a command line interface for federated server."""

import argparse
import logging
import os

from nvflare.apis.fl_constant import MachineStatus
from nvflare.fuel.common.excepts import ConfigError
from nvflare.fuel.utils.argument_utils import parse_vars
from nvflare.private.fed.app.fl_conf import FLServerStarterConfiger
from nvflare.private.fed.server.server_command_agent import ServerCommandAgent
from nvflare.private.fed.server.server_engine import ServerEngine
from nvflare.private.fed.server.server_json_config import ServerJsonConfigurator
from nvflare.private.fed.server.server_status import ServerStatus
from nvflare.private.fed.utils.fed_utils import add_logfile_handler


def main():
    """FL Server program starting point."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", "-m", type=str, help="WORKSPACE folder", required=True)

    parser.add_argument(
        "--fed_server", "-s", type=str, help="an aggregation server specification json file", required=True
    )
    parser.add_argument("--app_root", "-r", type=str, help="App Root", required=True)
    parser.add_argument("--run_number", "-n", type=str, help="RUn_number", required=True)
    # parser.add_argument("--snapshot", "-t", type=bool, help="snapshot", required=True)
    parser.add_argument("--port", "-p", type=str, help="listen port", required=True)
    parser.add_argument("--conn", "-c", type=str, help="connection port", required=True)

    parser.add_argument("--set", metavar="KEY=VALUE", nargs="*")

    args = parser.parse_args()
    kv_list = parse_vars(args.set)

    config_folder = kv_list.get("config_folder", "")
    if config_folder == "":
        args.server_config = "config_fed_server.json"
    else:
        args.server_config = config_folder + "/config_fed_server.json"
    args.env = "config/environment.json"
    args.config_folder = config_folder
    logger = logging.getLogger()
    args.log_config = None
    args.snapshot = kv_list.get("restore_snapshot")

    command_agent = None
    try:
        os.chdir(args.workspace)

        startup = os.path.join(args.workspace, "startup")
        conf = FLServerStarterConfiger(
            app_root=startup,
            server_config_file_name=args.fed_server,
            log_config_file_name="log.config",
            kv_list=args.set,
        )
        log_level = os.environ.get("FL_LOG_LEVEL", "")
        numeric_level = getattr(logging, log_level.upper(), None)
        if isinstance(numeric_level, int):
            logging.getLogger().setLevel(numeric_level)
            logger.debug("loglevel debug enabled")
            logger.info("loglevel info enabled")
            logger.warning("loglevel warn enabled")
            logger.error("loglevel error enabled")
            logger.critical("loglevel critical enabled")
        conf.configure()

        log_file = os.path.join(args.workspace, args.run_number, "log.txt")
        add_logfile_handler(log_file)

        deployer = conf.deployer
        secure_train = conf.cmd_vars.get("secure_train", False)

        try:
            # create the FL server
            _, server = deployer.create_fl_server(args, secure_train=secure_train)

            command_agent = ServerCommandAgent(int(args.port))
            command_agent.start(server.engine)

            snapshot = None
            if args.snapshot:
                fl_snapshot = server.snapshot_persistor.retrieve()
                if fl_snapshot:
                    snapshot = fl_snapshot.get_snapshot(args.run_number)

            start_server_app(server, args, args.app_root, args.run_number, snapshot)
        finally:
            command_agent.shutdown()
            deployer.close()

    except ConfigError as ex:
        print("ConfigError:", str(ex))
    finally:
        pass


def start_server_app(server, args, app_root, run_number, snapshot):

    try:
        server_config_file_name = os.path.join(app_root, args.server_config)

        conf = ServerJsonConfigurator(
            config_file_name=server_config_file_name,
        )
        conf.configure()

        set_up_run_config(server, conf)

        if not isinstance(server.engine, ServerEngine):
            raise TypeError(f"server.engine must be ServerEngine. Got type:{type(server.engine).__name__}")
        server.engine.create_parent_connection(int(args.conn))

        server.start_run(run_number, app_root, conf, args, snapshot)
    except BaseException as e:
        logging.getLogger().warning("FL server execution exception: " + str(e))
    finally:
        server.status = ServerStatus.STOPPED
        server.engine.engine_info.status = MachineStatus.STOPPED
        server.stop_training()


def set_up_run_config(server, conf):
    server.heart_beat_timeout = conf.heartbeat_timeout
    server.runner_config = conf.runner_config
    server.handlers = conf.handlers


if __name__ == "__main__":
    """
    This is the program when starting the child process for running the NVIDIA FLARE server runner.
    """
    main()