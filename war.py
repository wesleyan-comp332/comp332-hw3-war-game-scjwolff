"""
war card game client and server
"""
import asyncio
from collections import namedtuple
from enum import Enum
import logging
import random
import socket
import socketserver
import threading
import sys


"""
Namedtuples work like classes, but are much more lightweight so they end
up being faster. It would be a good idea to keep objects in each of these
for each game which contain the game's state, for instance things like the
socket, the cards given, the cards still available, etc.
"""
Game = namedtuple("Game", ["p1", "p2"])

# Stores the clients waiting to get connected to other clients
waiting_clients = []


class Command(Enum):
    """
    The byte values sent as the first byte of any message in the war protocol.
    """
    WANTGAME = 0
    GAMESTART = 1
    PLAYCARD = 2
    PLAYRESULT = 3


class Result(Enum):
    """
    The byte values sent as the payload byte of a PLAYRESULT message.
    """
    WIN = 0
    DRAW = 1
    LOSE = 2

def readexactly(sock, numbytes):
    """
    Accumulate exactly `numbytes` from `sock` and return those. If EOF is found
    before numbytes have been received, be sure to account for that here or in
    the caller.
    """
    data = b''
    while len(data) < numbytes:
        chunk = sock.recv(numbytes - len(data))
        if not chunk:
            raise ConnectionError("Connection closed before receiving enough data.")
        data += chunk
    return data


def kill_game(game):
    """
    TODO: If either client sends a bad message, immediately nuke the game.
    """
    try:
        game.p1.close()
    except:
        pass
    try:
        game.p2.close()
    except:
        pass


def compare_cards(card1, card2):
    """
    TODO: Given an integer card representation, return -1 for card1 < card2,
    0 for card1 = card2, and 1 for card1 > card2
    """
    def rank(card):
        return card % 13  # 0 for 2, ... 12 for Ace
    r1, r2 = rank(card1), rank(card2)
    if r1 > r2:
        return 1
    elif r1 < r2:
        return -1
    else:
        return 0
    

def deal_cards():
    """
    TODO: Randomize a deck of cards (list of ints 0..51), and return two
    26 card "hands."
    """
    deck = list(range(52))
    random.shuffle(deck)
    return deck[:26], deck[26:]
    
def run_game(game):
    try:
        p1, p2 = game.p1, game.p2

        # Expect "want game" from both clients
        if readexactly(p1, 2)[0] != Command.WANTGAME.value or readexactly(p2, 2)[0] != Command.WANTGAME.value:
            kill_game(game)
            return

        # Deal cards
        hand1, hand2 = deal_cards()
        p1.sendall(bytes([Command.GAMESTART.value]) + bytes(hand1))
        p2.sendall(bytes([Command.GAMESTART.value]) + bytes(hand2))

        used1, used2 = set(), set()
        for _ in range(26):
            msg1 = readexactly(p1, 2)
            msg2 = readexactly(p2, 2)

            if msg1[0] != Command.PLAYCARD.value or msg2[0] != Command.PLAYCARD.value:
                kill_game(game)
                return

            card1, card2 = msg1[1], msg2[1]

            # Ensure valid card
            if card1 not in hand1 or card1 in used1 or card2 not in hand2 or card2 in used2:
                kill_game(game)
                return

            used1.add(card1)
            used2.add(card2)

            cmp = compare_cards(card1, card2)
            if cmp == 1:
                result1, result2 = Result.WIN, Result.LOSE
            elif cmp == -1:
                result1, result2 = Result.LOSE, Result.WIN
            else:
                result1 = result2 = Result.DRAW

            p1.sendall(bytes([Command.PLAYRESULT.value, result1.value]))
            p2.sendall(bytes([Command.PLAYRESULT.value, result2.value]))

        p1.close()
        p2.close()

    except Exception as e:
        logging.error(f"Game error: {e}")
        kill_game(game)


'''
EXTRA CREDIT!
This implementation supports multiple games simultaneously by launching each game in its own 
thread using threading.Thread. When two clients connect, they are paired off and handled independently of other games
'''
def serve_game(host, port):
    """
    TODO: Open a socket for listening for new connections on host:port, and
    perform the war protocol to serve a game of war between each client.
    This function should run forever, continually serving clients.
    """
    server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server_sock.bind((host, port))
    server_sock.listen()
    logging.info(f"Server listening on {host}:{port}")

    while True:
        client_sock, addr = server_sock.accept()
        logging.info(f"Client connected: {addr}")
        waiting_clients.append(client_sock)

        if len(waiting_clients) >= 2:
            p1 = waiting_clients.pop(0)
            p2 = waiting_clients.pop(0)
            game = Game(p1, p2)
            threading.Thread(target=run_game, args=(game,), daemon=True).start()
    

async def limit_client(host, port, loop, sem):
    """
    Limit the number of clients currently executing.
    You do not need to change this function.
    """
    async with sem:
        return await client(host, port, loop)

async def client(host, port, loop):
    """
    Run an individual client on a given event loop.
    You do not need to change this function.
    """
    try:
        reader, writer = await asyncio.open_connection(host, port)
        # send want game
        writer.write(b"\0\0")
        card_msg = await reader.readexactly(27)
        myscore = 0
        for card in card_msg[1:]:
            writer.write(bytes([Command.PLAYCARD.value, card]))
            result = await reader.readexactly(2)
            if result[1] == Result.WIN.value:
                myscore += 1
            elif result[1] == Result.LOSE.value:
                myscore -= 1
        if myscore > 0:
            result = "won"
        elif myscore < 0:
            result = "lost"
        else:
            result = "drew"
        logging.debug("Game complete, I %s", result)
        writer.close()
        return 1
    except ConnectionResetError:
        logging.error("ConnectionResetError")
        return 0
    except asyncio.streams.IncompleteReadError:
        logging.error("asyncio.streams.IncompleteReadError")
        return 0
    except OSError:
        logging.error("OSError")
        return 0

def main(args):
    """
    launch a client/server
    """
    host = args[1]
    port = int(args[2])
    if args[0] == "server":
        try:
            # your server should serve clients until the user presses ctrl+c
            serve_game(host, port)
        except KeyboardInterrupt:
            pass
        return
    else:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
        
        asyncio.set_event_loop(loop)
        
    if args[0] == "client":
        loop.run_until_complete(client(host, port, loop))
    elif args[0] == "clients":
        sem = asyncio.Semaphore(1000)
        num_clients = int(args[3])
        clients = [limit_client(host, port, loop, sem)
                   for x in range(num_clients)]
        async def run_all_clients():
            """
            use `as_completed` to spawn all clients simultaneously
            and collect their results in arbitrary order.
            """
            completed_clients = 0
            for client_result in asyncio.as_completed(clients):
                completed_clients += await client_result
            return completed_clients
        res = loop.run_until_complete(
            asyncio.Task(run_all_clients(), loop=loop))
        logging.info("%d completed clients", res)

    loop.close()

if __name__ == "__main__":
    # Changing logging to DEBUG
    logging.basicConfig(level=logging.DEBUG)
    main(sys.argv[1:])
