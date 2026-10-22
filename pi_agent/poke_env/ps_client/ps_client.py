"""This module defines a base class for communicating with showdown servers.
"""
import asyncio
import json
import logging
from asyncio import CancelledError, Event, Lock, create_task, sleep
from logging import Logger
from time import perf_counter
from typing import Any, List, Optional, Set

import requests
# The modern asyncio client: the legacy "websockets.client" implementation
# hangs on connect with recent websockets releases.
import websockets as ws
from websockets import ClientConnection
from websockets.exceptions import ConnectionClosedOK

from poke_env.concurrency import (
    POKE_LOOP,
    create_in_poke_loop,
    handle_threaded_coroutines,
)
from poke_env.exceptions import ShowdownException
from poke_env.ps_client.account_configuration import AccountConfiguration
from poke_env.ps_client.server_configuration import ServerConfiguration


class PSClient:
    """
    Pokemon Showdown client.

    Responsible for communicating with showdown servers. Also implements some higher
    level methods for basic tasks, such as changing avatar and low-level message
    handling.
    """

    def __init__(
        self,
        account_configuration: AccountConfiguration,
        *,
        avatar: Optional[int] = None,
        log_level: Optional[int] = None,
        server_configuration: ServerConfiguration,
        start_listening: bool = True,
        ping_interval: Optional[float] = 20.0,
        ping_timeout: Optional[float] = 20.0,
    ):
        """
        :param account_configuration: Account configuration.
        :type account_configuration: AccountConfiguration
        :param avatar: Player avatar id. Optional.
        :type avatar: int, optional
        :param log_level: The player's logger level.
        :type log_level: int. Defaults to logging's default level.
        :param server_configuration: Server configuration.
        :type server_configuration: ServerConfiguration
        :param start_listening: Whether to start listening to the server. Defaults to
            True.
        :type start_listening: bool
        :param ping_interval: How long between keepalive pings (Important for backend
            websockets). If None, disables keepalive entirely.
        :type ping_interval: float, optional
        :param ping_timeout: How long to wait for a timeout of a specific ping
            (important for backend websockets.
            Increase only if timeouts occur during runtime).
            If None pings will never time out.
        :type ping_timeout: float, optional
        """
        self._active_tasks: Set[Any] = set()
        self._ping_interval = ping_interval
        self._ping_timeout = ping_timeout
        # Websocket connect retries, see listen()
        self._max_connection_attempts = 4
        self._connection_retry_delay = 5.0
        self._authentication_timeout = 30.0

        self._server_configuration = server_configuration
        self._account_configuration = account_configuration

        self._avatar = avatar

        self._logged_in: Event = create_in_poke_loop(Event)
        self._sending_lock = create_in_poke_loop(Lock)

        self.websocket: ClientConnection
        self._logger: Logger = self._create_logger(log_level)
        # self._logger.setLevel(logging.DEBUG)

        if start_listening:
            self._listening_coroutine = asyncio.run_coroutine_threadsafe(
                self.listen(), POKE_LOOP
            )

    async def accept_challenge(self, username: str, packed_team: Optional[str]):
        assert (
            self.logged_in.is_set()
        ), f"Expected player {self.username} to be logged in."
        # Store challenge info for potential retry after team rejection
        if hasattr(self, '_handle_team_rejection'):
            self._last_challenge_info = ('accept', username, None, packed_team)
        await self.set_team(packed_team)
        await self.send_message("/accept %s" % username)

    async def challenge(self, username: str, format_: str, packed_team: Optional[str]):
        assert (
            self.logged_in.is_set()
        ), f"Expected player {self.username} to be logged in."
        # Store challenge info for potential retry after team rejection
        if hasattr(self, '_handle_team_rejection'):
            self._last_challenge_info = ('challenge', username, format_, packed_team)
        await self.set_team(packed_team)
        await self.send_message(f"/challenge {username}, {format_}")

    def _create_logger(self, log_level: Optional[int]) -> Logger:
        """Creates a logger for the client.

        Returns a Logger displaying asctime and the account's username before messages.

        :param log_level: The logger's level.
        :type log_level: int
        :return: The logger.
        :rtype: Logger
        """
        logger = logging.getLogger(self.username)

        stream_handler = logging.StreamHandler()
        if log_level is not None:
            logger.setLevel(log_level)

        formatter = logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        )
        stream_handler.setFormatter(formatter)

        logger.addHandler(stream_handler)
        return logger

    async def _handle_message(self, message: str):
        """Handle received messages.

        :param message: The message to parse.
        :type message: str
        """
        try:
            # Showdown websocket messages are pipe-separated sequences
            split_messages = [m.split("|") for m in message.split("\n")]
            # The type of message is determined by the first entry in the message
            # For battles, this is the zero-th entry
            # Otherwise it is the one-th entry
            if split_messages[0][0].startswith(">battle"):
                # Battle update
                # if self.username == 'SimpleHeuristics 1':
                    # print("pause")
                await self._handle_battle_message(split_messages)  # type: ignore
            elif split_messages[0][1] == "challstr":
                # Confirms connection to the server: we can login
                await self.log_in(split_messages[0])
            elif split_messages[0][1] == "updateuser":
                if split_messages[0][2] in [
                    " " + self.username,
                    " " + self.username + "@!",
                ]:
                    # Confirms successful login
                    self.logged_in.set()
                elif not split_messages[0][2].startswith(" Guest "):
                    self.logger.warning(
                        """Trying to login as %s, showdown returned %s """
                        """- this might prevent future actions from this agent. """
                        """Changing the agent's username might solve this problem.""",
                        self.username,
                        split_messages[0][2],
                    )
            elif "updatechallenges" in split_messages[0][1]:
                # Contain information about current challenge
                await self._update_challenges(split_messages[0])  # type: ignore
            elif split_messages[0][1] == "updatesearch":
                pass
            elif split_messages[0][1] == "popup":
                self.logger.warning("Popup message received: %s", message)
                # Check if this is a team rejection message
                if "team was rejected" in message.lower():
                    # Notify the player about team rejection if handler exists
                    if hasattr(self, '_handle_team_rejection'):
                        await self._handle_team_rejection(message)  # type: ignore
            elif split_messages[0][1] in ["nametaken"]:
                self.logger.critical("SKIPPED Error message received: %s", message)
                # raise ShowdownException("Error message received: %s", message)
            elif split_messages[0][1] == "pm":
                if len(split_messages) == 1:
                    if split_messages[0][4].startswith("/challenge"):
                        await self._handle_challenge_request(split_messages[0])  # type: ignore
                    elif split_messages[0][4].startswith("/text"):
                        self.logger.info("Received pm with text: %s", message)
                    elif split_messages[0][4].startswith("/nonotify"):
                        self.logger.info("Received pm: %s", message)
                    elif split_messages[0][4].startswith("/log"):
                        self.logger.info("Received pm: %s", message)
                    else:
                        self.logger.warning("Received pm: %s", message)
                elif len(split_messages) == 2:
                    self.logger.info("Received pm: %s", message)
                else:
                    raise ValueError(
                        f"Expected len({split_messages}) to be 1 or 2, got {len(split_messages)}"
                    )
            else:
                self.logger.warning("Unhandled message: %s", message)
        except CancelledError as e:
            self.logger.critical("CancelledError intercepted: %s", e)
        except Exception as exception:
            self.logger.exception(
                "Unhandled exception raised while handling message:\n%s", message
            )
            raise exception

    async def _stop_listening(self):
        await self.websocket.close()

    async def change_avatar(self, avatar_id: Optional[int]):
        """Changes the player's avatar.

        :param avatar_id: The new avatar id. If None, nothing happens.
        :type avatar_id: int
        """
        await self.wait_for_login()
        if avatar_id is not None:
            await self.send_message(f"/avatar {avatar_id}")

    async def listen(self):
        """Listen to a showdown websocket and dispatch messages to be handled."""
        self.logger.info("Starting listening to showdown websocket")
        if 'localhost' not in self.server_configuration.server_url:
            self.websocket_url = self.websocket_url_online
        else:
            self.websocket_url = self.websocket_url_local
        # The challenge server occasionally resets the TLS handshake. Without a
        # retry the player stays stuck on "waiting for log in" forever, so try a
        # few times before giving up.
        for attempt in range(1, self._max_connection_attempts + 1):
            try:
                async with ws.connect(
                    self.websocket_url,
                    max_queue=None,
                    ping_interval=self._ping_interval,
                    ping_timeout=self._ping_timeout,
                ) as websocket:
                    self.websocket = websocket
                    async for message in websocket:
                        self.logger.info("\033[92m\033[1m<<<\033[0m %s", message)
                        task = create_task(self._handle_message(str(message)))
                        self._active_tasks.add(task)
                        task.add_done_callback(self._active_tasks.discard)
                return

            except ConnectionClosedOK:
                self.logger.warning(
                    "Websocket connection with %s closed", self.websocket_url
                )
                return
            except (CancelledError, RuntimeError) as e:
                self.logger.critical("Listen interrupted by %s", e)
                return
            except Exception as e:
                self.logger.warning(
                    "Websocket connection to %s failed (attempt %s/%s): %s",
                    self.websocket_url,
                    attempt,
                    self._max_connection_attempts,
                    e,
                )
                if attempt == self._max_connection_attempts:
                    self.logger.exception(e)
                    return
                await asyncio.sleep(self._connection_retry_delay)

    async def _authenticate(self, split_message: List[str]) -> "requests.Response":
        """Request a login assertion from the authentication endpoint.

        The endpoint occasionally resets the connection, which used to make the
        player hang on "waiting for log in", so retry a few times.
        """
        data = {
            "act": "login",
            "name": self.account_configuration.username,
            "pass": self.account_configuration.password,
            "challstr": split_message[2] + "%7C" + split_message[3],
        }
        last_error: Optional[Exception] = None
        for attempt in range(1, self._max_connection_attempts + 1):
            try:
                self.logger.info("Sending authentication request (attempt %s)", attempt)
                return requests.post(
                    self.server_configuration.authentication_url,
                    data=data,
                    timeout=self._authentication_timeout,
                )
            except requests.RequestException as e:
                last_error = e
                self.logger.warning(
                    "Authentication request failed (attempt %s/%s): %s",
                    attempt,
                    self._max_connection_attempts,
                    e,
                )
                if attempt < self._max_connection_attempts:
                    await asyncio.sleep(self._connection_retry_delay)
        raise last_error

    async def log_in(self, split_message: List[str]):
        """Log the player with specified username and password.

        Split message contains information sent by the server. This information is
        necessary to log in.

        :param split_message: Message received from the server that triggers logging in.
        :type split_message: List[str]
        """
        if self.account_configuration.password:
            log_in_request = await self._authenticate(split_message)
            assertion = json.loads(log_in_request.text[1:])["assertion"]
        else:
            self.logger.info("Bypassing authentication request")
            assertion = ""

        await self.send_message(f"/trn {self.username},0,{assertion}")

        await self.change_avatar(self._avatar)

    async def search_ladder_game(self, format_: str, packed_team: Optional[str]):
        await self.set_team(packed_team)
        await self.send_message(f"/search {format_}")

    async def send_message(
        self, message: str, room: str = "", message_2: Optional[str] = None
    ):
        """Sends a message to the specified room.

        `message_2` can be used to send a sequence of length 2.

        :param message: The message to send.
        :type message: str
        :param room: The room to which the message should be sent.
        :type room: str
        :param message_2: Second element of the sequence to be sent. Optional.
        :type message_2: str, optional
        """
        if message_2:
            to_send = "|".join([room, message, message_2])
        else:
            to_send = "|".join([room, message])
        await self.websocket.send(to_send)

    async def set_team(self, packed_team: Optional[str]):
        if packed_team:
            await self.send_message(f"/utm {packed_team}")
        else:
            await self.send_message("/utm null")

    async def stop_listening(self):
        await handle_threaded_coroutines(self._stop_listening())

    async def wait_for_login(self, checking_interval: float = 0.001, wait_for: int = 5):
        start = perf_counter()
        while perf_counter() - start < wait_for:
            await sleep(checking_interval)
            if self.logged_in:
                return
        assert self.logged_in, f"Expected player {self.username} to be logged in."

    @property
    def account_configuration(self) -> AccountConfiguration:
        """The client's account configuration.

        :return: The client's account configuration.
        :rtype: AccountConfiguration
        """
        return self._account_configuration

    @property
    def logged_in(self) -> Event:
        """Event object associated with user login.

        :return: The logged-in event
        :rtype: Event
        """
        return self._logged_in

    @property
    def logger(self) -> Logger:
        """Logger associated with the player.

        :return: The logger.
        :rtype: Logger
        """
        return self._logger

    @property
    def server_configuration(self) -> ServerConfiguration:
        """The client's server configuration.

        :return: The client's server configuration.
        :rtype: ServerConfiguration
        """
        return self._server_configuration

    @property
    def username(self) -> str:
        """The player's username.

        :return: The player's username.
        :rtype: str
        """
        return self.account_configuration.username

    @property
    def websocket_url_online(self) -> str:
        """The websocket url for online connections.

        It is derived from the server url.

        :return: The websocket url.
        :rtype: str
        """
        # return f"ws://{self.server_configuration.server_url}/showdown/websocket"   # online
        return f"wss://{self.server_configuration.server_url}/showdown/websocket"   # online

    @property
    def websocket_url_local(self) -> str:
        """The websocket url for local connections.

        It is derived from the server url.

        :return: The websocket url.
        :rtype: str
        """
        return f"ws://{self.server_configuration.server_url}/showdown/websocket"  # local
    
