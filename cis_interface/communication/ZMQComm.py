import uuid
import zmq
import threading
import logging
from cis_interface import backwards, tools
from cis_interface.communication import CommBase, AsyncComm


_register_socket_lock = threading.RLock()
_registered_sockets = dict()
_created_sockets = dict()


_socket_type_pairs = [('PUSH', 'PULL'),
                      ('PUB', 'SUB'),
                      ('REP', 'REQ'),
                      ('ROUTER', 'DEALER'),
                      ('PAIR', 'PAIR')]
_socket_send_types = [t[0] for t in _socket_type_pairs]
_socket_recv_types = [t[1] for t in _socket_type_pairs]
_socket_protocols = ['tcp', 'inproc', 'ipc', 'udp', 'pgm', 'epgm']
_flag_zmq_filter = backwards.unicode2bytes('_ZMQFILTER_')
_default_socket_type = 4
_default_protocol = 'tcp'
_wait_send_t = 0  # 0.0001
_reply_msg = backwards.unicode2bytes('CIS_REPLY')
_purge_msg = backwards.unicode2bytes('CIS_PURGE')


def cleanup_comms():
    r"""Close registered sockets."""
    with _register_socket_lock:
        global _registered_sockets
        count = 0
        for v in _registered_sockets.values():
            if not v.closed:
                v.close(linger=0)
                count += 1
        _registered_sockets = dict()
        return count


def register_socket(socket_type_name, address, socket):
    r"""Register a socket.

    Args:
        socket_type_name (str): Name of the socket type.
        address (str): Socket address.
        socket (zmq.Socket): Socket object.

    """
    with _register_socket_lock:
        global _registered_sockets
        key = '%s_%s' % (socket_type_name, address)
        _registered_sockets[key] = socket

    
def unregister_socket(socket_type_name, address, linger=0):
    r"""Unregister a socket.

    Args:
        socket_type_name (str): Name of the socket type.
        address (str): Socket address.
        linger (int, optional): Time in milliseconds that socket should
            linger on close. Defaults to 0.

    """
    with _register_socket_lock:
        global _registered_sockets
        key = '%s_%s' % (socket_type_name, address)
        if key in _registered_sockets:
            if not _registered_sockets[key].closed:
                _registered_sockets[key].close(linger=linger)
            _registered_sockets.pop(key)
            # del _registered_sockets[key]

        
def get_socket_type_mate(t_in):
    r"""Find the counterpart socket type.

    Args:
        t_in (str): Socket type.

    Returns:
        str: Counterpart socket type.

    Raises:
        ValueError: If t_in is not a recognized socket type.

    """
    if t_in in _socket_send_types:
        for t in _socket_type_pairs:
            if t[0] == t_in:
                return t[1]
    elif t_in in _socket_recv_types:
        for t in _socket_type_pairs:
            if t[1] == t_in:
                return t[0]
    else:
        raise ValueError('Could not locate socket type %s' % t_in)


def format_address(protocol, host, port=None):
    r"""Format an address based on its parts.

    Args:
        protocol (str): Communication protocol that should be used.
        host (str): Host that address should point to.
        port (int, optional): Port that address should point to. Defaults to
            None and is not added to the address.

    Returns:
        str: Complete address.

    Raises:
        ValueError: If the protocol is not recognized.

    """
    if host == 'localhost':
        host = '127.0.0.1'
    if protocol in ['inproc', 'ipc']:
        address = "%s://%s" % (protocol, host)
    elif protocol not in _socket_protocols:
        raise ValueError("Unrecognized protocol: %s" % protocol)
    else:
        address = "%s://%s" % (protocol, host)
        if port is not None:
            address += ":%d" % port
    return address

                    
def parse_address(address):
    r"""Split an address into its parts.

    Args:
        address (str): Address to be split.

    Returns:
        dict: Parameters extracted from the address.

    Raises:
        ValueError: If the address dosn't contain '://'.
        ValueError: If the protocol is not supported.

    """
    if '://' not in address:
        raise ValueError("Address must contain '://'")
    protocol, res = address.split('://')
    if protocol not in _socket_protocols:
        raise ValueError("Protocol '%s' not supported." % protocol)
    if protocol in ['inproc', 'ipc']:
        host = res
        port = protocol
    else:
        if ':' in res:
            host, port = res.split(':')
            port = int(port)
        else:
            host = res
            port = None
    out = dict(protocol=protocol, host=host, port=port)
    return out


def bind_socket(socket, address, retry_timeout=-1):
    r"""Bind a socket to an address, getting a random port as necessary.

    Args:
        socket (zmq.Socket): Socket that should be bound.
        address (str): Address that socket should be bound to.
        retry_timeout (float, optional): Time (in seconds) that should be
            waited before retrying to bind the socket to the address. If
            negative, a retry will not be attempted and an error will be
            raised. Defaults to -1;

    Returns:
        str: Address that socket was bound to, including random port if one
            was used.

    """
    try:
        param = parse_address(address)
        if (param['protocol'] in ['inproc', 'ipc']) or (param['port'] is not None):
            socket.bind(address)
        else:
            port = socket.bind_to_random_port(address)
            address += ":%d" % port
    except zmq.ZMQError as e:
        if (e.errno not in [48, 98]) or (retry_timeout < 0):
            raise e
        else:
            logging.debug("Retrying bind in %f s", retry_timeout)
            tools.sleep(retry_timeout)
            address = bind_socket(socket, address)
    return address

    
class ZMQProxy(CommBase.CommServer):
    r"""Start a proxy in a new thread for a server address. A client-side
    address will be randomly generated.

    Args:
        srv_address (str): Address that should face the server(s).
        context (zmq.Context, optional): ZeroMQ context that should be used.
            Defaults to None and the global context is used.
        protocol (str, optional): Protocol that should be used for the sockets.
            Defaults to None and is set to _default_protocol.
        host (str, optional): Host for socket address. Defaults to 'localhost'.
        retry_timeout (float, optional): Time (in seconds) that should be
            waited before retrying to bind the sockets to the addresses. If
            negative, a retry will not be attempted and an error will be
            raised. Defaults to -1;
        **kwargs: Additional keyword arguments are passed to the parent class.

    Attributes:
        srv_address (str): Address that faces the server(s).
        cli_address (str): Address that faces the client(s).
        context (zmq.Context): ZeroMQ context that will be used.
        srv_socket (zmq.Socket): Socket facing client(s).
        cli_socket (zmq.Socket): Socket facing server(s).
        cli_count (int): Number of clients that have connected to this proxy.

    """
    def __init__(self, srv_address, context=None, retry_timeout=-1, **kwargs):
        # Get parameters
        srv_param = parse_address(srv_address)
        cli_param = dict()
        for k in ['protocol', 'host', 'port']:
            cli_param[k] = kwargs.pop(k, srv_param[k])
        context = context or zmq.Context.instance()
        # Create new address for the frontend
        if cli_param['protocol'] in ['inproc', 'ipc']:
            cli_param['host'] = str(uuid.uuid4())
        cli_address = format_address(cli_param['protocol'], cli_param['host'])
        self.cli_socket = context.socket(zmq.ROUTER)
        self.cli_address = bind_socket(self.cli_socket, cli_address,
                                       retry_timeout=retry_timeout)
        self.cli_socket.setsockopt(zmq.LINGER, 0)
        register_socket('ROUTER_server', self.cli_address, self.cli_socket)
        # Bind backend
        self.srv_socket = context.socket(zmq.DEALER)
        self.srv_socket.setsockopt(zmq.LINGER, 0)
        self.srv_address = bind_socket(self.srv_socket, srv_address,
                                       retry_timeout=retry_timeout)
        register_socket('DEALER_server', self.srv_address, self.srv_socket)
        # Set up poller
        # self.poller = zmq.Poller()
        # self.poller.register(frontend, zmq.POLLIN)
        self.reply_socket = None
        # Set name
        super(ZMQProxy, self).__init__(self.srv_address, self.cli_address, **kwargs)
        self.name = 'ZMQProxy.%s' % srv_address

    def client_recv(self):
        r"""Receive single message from the client."""
        with self.lock:
            if not self.was_break:
                return self.cli_socket.recv_multipart()
            else:  # pragma: debug
                return None

    def server_send(self, msg):
        r"""Send single message to the server."""
        if msg is None:  # pragma: debug
            return
        while not self.was_break:
            try:
                self.srv_socket.send(msg, zmq.NOBLOCK)
                # self.srv_socket.send_multipart(msg, zmq.NOBLOCK)
                break
            except zmq.ZMQError:
                self.sleep(0.0001)

    def poll(self):
        # socks = dict(self.poller.poll())
        # return (socks.get(self.cli_socket) == zmq.POLLIN)
        with self.lock:
            if self.was_break:  # pragma: debug
                return False
        out = self.cli_socket.poll(timeout=1, flags=zmq.POLLIN)
        return (out == zmq.POLLIN)

    def run_loop(self):
        r"""Forward messages from client to server."""
        if self.poll():
            message = self.client_recv()
            if message is not None:
                self.debug('Forwarding message of size %d from %s',
                           len(message[1]), message[0])
                self.server_send(message[1])

    def after_loop(self):
        r"""Close sockets after the loop finishes."""
        self.cleanup()
        super(ZMQProxy, self).after_loop()

    def cleanup(self):
        r"""Clean up sockets on exit."""
        self.close_sockets()

    def close_sockets(self):
        r"""Close the sockets."""
        self.debug('Closing sockets')
        if self.cli_socket:
            self.cli_socket.close()
            self.cli_socket = None
        if self.srv_socket:
            self.srv_socket.close()
            self.srv_socket = None
        unregister_socket('ROUTER_server', self.cli_address)
        unregister_socket('DEALER_server', self.srv_address)


class ZMQComm(AsyncComm.AsyncComm):
    r"""Class for handling I/O using ZeroMQ sockets.

    Args:
        name (str): The environment variable where the socket address is
            stored.
        context (zmq.Context, optional): ZeroMQ context that should be used.
            Defaults to None and the global context is used.
        socket_type (str, optional): The type of socket that should be created.
            Defaults to _default_socket_type. See zmq for all options.
        socket_action (str, optional): The action that the socket should perform.
            Defaults to action based on the direction ('connect' for 'recv',
            'bind' for 'send'.)
        topic_filter (str, optional): Message filter to use when subscribing.
            This is only used for 'SUB' socket types. Defaults to '' which is
            all messages.
        dealer_identity (str, optional): Identity that should be used to route
            messages to a dealer socket. Defaults to '0'.
        **kwargs: Additional keyword arguments are passed to CommBase.

    Attributes:
        context (zmq.Context): ZeroMQ context that will be used.
        socket (zmq.Socket): ZeroMQ socket.
        socket_type_name (str): The type of socket that should be created.
        socket_type (int): ZeroMQ socket type.
        socket_action (str, optional): The action that the socket should perform.
        topic_filter (str): Message filter to use when subscribing.
        dealer_identity (str): Identity that should be used to route messages
            to a dealer socket.

    """
    
    def _init_before_open(self, context=None, socket_type=None,
                          socket_action=None, topic_filter='',
                          dealer_identity=None, **kwargs):
        r"""Initialize defaults for socket type/action based on direction."""
        self.socket_lock = threading.RLock()
        # Client/Server things
        if self.is_client:
            socket_type = 'DEALER'
            socket_action = 'connect'
            self.direction = 'send'
        if self.is_server:
            socket_type = 'DEALER'
            socket_action = 'connect'
            self.direction = 'recv'
        # Set defaults
        if socket_type is None:
            if self.direction == 'recv':
                socket_type = _socket_recv_types[_default_socket_type]
            elif self.direction == 'send':
                socket_type = _socket_send_types[_default_socket_type]
        if not (self.is_client or self.is_server):
            if socket_type in ['PULL', 'SUB', 'REP', 'DEALER']:
                self.direction = 'recv'
            elif socket_type in ['PUSH', 'PUB', 'REQ', 'ROUTER']:
                self.direction = 'send'
        if socket_action is None:
            if self.port in ['inproc', 'ipc']:
                if socket_type in ['PULL', 'SUB', 'REQ', 'DEALER']:
                    socket_action = 'connect'
                elif socket_type in ['PUSH', 'PUB', 'REP', 'ROUTER']:
                    socket_action = 'bind'
                else:
                    if self.direction == 'recv':
                        socket_action = 'connect'
                    elif self.direction == 'send':
                        socket_action = 'bind'
            elif self.port is None:
                socket_action = 'bind'
            else:
                socket_action = 'connect'
        self.context = context or zmq.Context.instance()
        self.socket_type_name = socket_type
        self.socket_type = getattr(zmq, socket_type)
        self.socket_action = socket_action
        self.socket = self.context.socket(self.socket_type)
        self.topic_filter = backwards.unicode2bytes(topic_filter)
        if dealer_identity is None:
            dealer_identity = str(uuid.uuid4())
        self.dealer_identity = backwards.unicode2bytes(dealer_identity)
        self._openned = False
        self._bound = False
        self._connected = False
        self._recv_identities = set([])
        # Reply socket attributes
        self.zmq_sleeptime = int(10000 * self.sleeptime)
        self.reply_socket_address = None
        self.reply_socket_send = None
        self.reply_socket_recv = {}
        self._n_zmq_sent = 0
        self._n_zmq_recv = {}
        self._n_reply_sent = 0
        self._n_reply_recv = {}
        self._server_class = ZMQProxy
        self._server_kwargs = dict(context=self.context,
                                   retry_timeout=4 * self.sleeptime)
        super(ZMQComm, self)._init_before_open(**kwargs)

    @classmethod
    def is_installed(cls):
        r"""bool: Is the comm installed."""
        return tools._zmq_installed

    @property
    def maxMsgSize(self):
        r"""int: Maximum size of a single message that should be sent."""
        # Based on limit of 32bit int, this could be 2**30, but this is
        # too large for stack allocation in C so 2**20 will be used.
        return 2**20

    @classmethod
    def comm_count(cls):
        r"""int: Number of sockets that have been opened on this process."""
        with _register_socket_lock:
            return len(_registered_sockets)

    @property
    def address_param(self):
        r"""dict: Address parameters."""
        return parse_address(self.address)

    @property
    def protocol(self):
        r"""str: Protocol that socket uses."""
        return self.address_param['protocol']

    @property
    def host(self):
        r"""str: Host that socket is connected to."""
        return self.address_param['host']

    @property
    def port(self):
        r"""str: Port that socket is connected to."""
        return self.address_param['port']

    @classmethod
    def new_comm_kwargs(cls, name, protocol=None, host=None, port=None, **kwargs):
        r"""Initialize communication with new queue.

        Args:
            name (str): Name of new socket.
            protocol (str, optional): The protocol that should be used.
                Defaults to None and is set to _default_protocol. See zmq for
                details.
            host (str, optional): The host that should be used. Invalid for
                'inproc' protocol. Defaults to 'localhost'.
            port (int, optional): The port used. Invalid for 'inproc' protocol.
                Defaults to None and a random port is choosen.
            **kwargs: Additional keywords arguments are returned as keyword
                arguments for the new comm.

        Returns:
            tuple(tuple, dict): Arguments and keyword arguments for new socket.

        """
        args = [name]
        if protocol is None:
            protocol = _default_protocol
        if host is None:
            if protocol in ['inproc', 'ipc']:
                host = str(uuid.uuid4())
            else:
                host = 'localhost'
        if 'address' not in kwargs:
            kwargs['address'] = format_address(protocol, host, port=port)
        return args, kwargs

    @property
    def opp_address(self):
        r"""str: Address for opposite comm."""
        if self.is_client:
            if self._server is None:  # pragma: debug
                raise Exception("The client proxy does not yet have an address.")
            return self._server.srv_address
        else:
            return self.address

    def opp_comm_kwargs(self):
        r"""Get keyword arguments to initialize communication with opposite
        comm object.

        Returns:
            dict: Keyword arguments for opposite comm object.

        """
        kwargs = super(ZMQComm, self).opp_comm_kwargs()
        kwargs['socket_type'] = get_socket_type_mate(self.socket_type_name)
        if self.is_client:
            kwargs['is_server'] = True
        elif self.is_server:
            kwargs['is_client'] = True
        if kwargs['socket_type'] in ['DEALER', 'ROUTER']:
            kwargs['dealer_identity'] = self.dealer_identity
        return kwargs

    def register_socket(self):
        r"""Register a socket."""
        self.debug('Registering socket: type = %s, address = %s',
                   self.socket_type_name, self.address)
        with self._closing_thread.lock:
            register_socket(self.socket_type_name, self.address, self.socket)

    def unregister_socket(self, linger=0):
        r"""Unregister a socket."""
        self.debug('Unregistering socket: type = %s, address = %s',
                   self.socket_type_name, self.address)
        with self._closing_thread.lock:
            unregister_socket(self.socket_type_name, self.address, linger=linger)
        
    def bind(self):
        r"""Bind to address, getting random port as necessary."""
        super(ZMQComm, self).bind()
        if self.is_open or self._bound or self._connected:  # pragma: debug
            return
        # Bind to reserve port if that is this sockets action
        with self.socket_lock:
            if (self.socket_action == 'bind') or (self.port is None):
                self._bound = True
                self.debug('Binding %s socket to %s.',
                           self.socket_type_name, self.address)
                try:
                    self.address = bind_socket(self.socket, self.address,
                                               retry_timeout=2 * self.sleeptime)
                except zmq.ZMQError as e:
                    if (self.socket_type_name == 'PAIR') and (e.errno == 98):
                        self.error(("There is already a 'PAIR' socket sending " +
                                    "to %s. Maybe you meant to create a recv " +
                                    "PAIR?") % self.address)
                    self._bound = False
                    raise e
                self.debug('Bound %s socket to %s.',
                           self.socket_type_name, self.address)
                # Unbind if action should be connect
                if self.socket_action == 'connect':
                    self.unbind()
            else:
                self._bound = False
            if self._bound:
                self.register_socket()

    def connect(self):
        r"""Connect to address."""
        if self.is_open or self._bound or self._connected:  # pragma: debug
            return
        with self.socket_lock:
            if (self.socket_action == 'connect'):
                self._connected = True
                self.debug("Connecting %s socket to %s",
                           self.socket_type_name, self.address)
                self.socket.connect(self.address)
            if self._connected:
                self.register_socket()

    def unbind(self, linger=0):
        r"""Unbind from address."""
        with self.socket_lock:
            if self._bound:
                self.debug('Unbinding from %s' % self.address)
                try:
                    self.socket.unbind(self.address)
                except zmq.ZMQError:  # pragma: debug
                    pass
                self.unregister_socket(linger=linger)
                self._bound = False
            self.debug('Unbound socket')

    # def disconnect(self, linger=0):
    #     r"""Disconnect from address."""
    #     if self._connected:
    #         self.debug('Disconnecting from %s' % self.address)
    #         try:
    #             self.socket.disconnect(self.address)
    #         except zmq.ZMQError:  # pragma: debug
    #             pass
    #         self.unregister_socket(linger=linger)
    #         self._connected = False
    #     self.debug('Disconnected socket')

    def _open_direct(self):
        r"""Open connection by binding/connect to the specified socket."""
        super(ZMQComm, self)._open_direct()
        with self.socket_lock:
            if not self.is_open_direct:
                # Set dealer identity
                if self.socket_type_name == 'DEALER':
                    self.socket.setsockopt(zmq.IDENTITY, self.dealer_identity)
                # Bind/connect
                if self.socket_action == 'bind':
                    self.bind()
                elif self.socket_action == 'connect':
                    # Bind then unbind to get port as necessary
                    self.bind()
                    self.unbind()
                    self.connect()
                # Set topic filter
                if self.socket_type_name == 'SUB':
                    self.socket.setsockopt(zmq.SUBSCRIBE, self.topic_filter)
                self._openned = True

    def check_reply_socket_send(self, msg):
        r"""Append reply socket address if it

        Args:
            msg (str): Message that will be piggy backed on.

        Returns:
            str: Message with reply address if it has not been sent.


        """
        if self.direction == 'recv':
            return msg
        # Create socket
        if self.reply_socket_send is None:
            self.reply_socket_send = self.context.socket(zmq.REP)
            address = format_address(_default_protocol, 'localhost')
            address = bind_socket(self.reply_socket_send, address)
            self.reply_socket_address = address
            self.debug("new send address: %s", address)
        new_msg = backwards.format_bytes(
            backwards.unicode2bytes(':%s:%s:%s:'), (
                _reply_msg, self.reply_socket_address,
                _reply_msg))
        new_msg += msg
        return new_msg
        
    def check_reply_socket_recv(self, msg):
        r"""Check incoming message for reply address.

        Args:
            msg (str): Incoming message to check.

        Returns:
            str: Messages with reply address removed if present.

        """
        if self.direction == 'send':
            return msg, None
        prefix = backwards.format_bytes(
            backwards.unicode2bytes(':%s:'), (_reply_msg,))
        if msg.startswith(prefix):
            _, address, new_msg = msg.split(prefix)
            if address not in self.reply_socket_recv:
                self.reply_socket_recv[address] = self.context.socket(zmq.REQ)
                self.reply_socket_recv[address].connect(address)
                self._n_reply_recv[address] = 0
                self._n_zmq_recv[address] = 0
            self.debug("new recv address: %s", address)
        else:  # pragma: debug
            new_msg = msg
            raise Exception("No reply socket address attached.")
        return new_msg, address

    # @property
    # def n_reply_sent(self):
    #     r"""Number of messages sent which have been confirmed."""
    #     return self._n_reply_sent

    # @property
    # def n_reply_recv(self):
    #     r"""Number of messages received which have been confirmed."""
    #     return sum(self._n_reply_recv.values())

    def _reply_handshake_send(self):
        r"""Do send side of handshake."""
        if (((self.reply_socket_send is None) or
             self.reply_socket_send.closed)):  # pragma: debug
            self.backlog_thread.set_break_flag()
            self.debug("SOCKET CLOSED")
            return False
        out = self.reply_socket_send.poll(timeout=1, flags=zmq.POLLIN)
        if out == 0:
            return False
        msg = self.reply_socket_send.recv(flags=zmq.NOBLOCK)
        if msg == self.eof_msg:  # pragma: debug
            self.error("REPLY EOF RECV'D")
            return msg
        self.reply_socket_send.send(msg, flags=zmq.NOBLOCK)
        self._n_reply_sent += 1
        return msg

    def _reply_handshake_recv(self, msg_send, key):
        r"""Do recv side of handshake."""
        try:
            socket = self.reply_socket_recv.get(key, None)
            if socket is None or socket.closed:  # pragma: debug
                self.backlog_thread.set_break_flag()
                self.debug("SOCKET CLOSED")
                return False
            out = socket.poll(timeout=1, flags=zmq.POLLOUT)
            if out == 0:  # pragma: debug
                return False
            socket.send(msg_send, flags=zmq.NOBLOCK)
            if msg_send == self.eof_msg:  # pragma: debug
                self.error("REPLY EOF SENT")
                return True
            out = socket.poll(timeout=self.zmq_sleeptime, flags=zmq.POLLIN)
            if out == 0:
                return False
            msg_recv = socket.recv(flags=zmq.NOBLOCK)
            assert(msg_recv == msg_send)
            self._n_reply_recv[key] += 1
            return True
        except zmq.ZMQError:  # pragma: debug
            return False

    def _close_direct(self, linger=False):
        r"""Close the connection.

        Args:
            linger (bool, optional): If True, drain messages before closing the
                comm. Defaults to False.

        """
        with self.socket_lock:
            self.debug("self.socket.closed = %s", str(self.socket.closed))
            if self.socket.closed:
                self._bound = False
                self._connected = False
            # else:
            #     if self.socket_action == 'bind':
            #         self.unbind()
            #     elif self.socket_action == 'connect':
            #         self.disconnect()
            # Ensure socket not still open
            self._openned = False
            self.unregister_socket(linger=0)
            if not self.socket.closed:
                self.socket.close(linger=0)
        super(ZMQComm, self)._close_direct(linger=linger)

    def _close_backlog(self, wait=False):
        r"""Close the backlog thread and the reply sockets."""
        super(ZMQComm, self)._close_backlog(wait=wait)
        if self.direction == 'send':
            if (self.reply_socket_send is not None):
                self.reply_socket_send.close(linger=self.zmq_sleeptime)
        else:
            for k, socket in self.reply_socket_recv.items():
                socket.close(linger=0)

    def server_exists(self, srv_address):
        r"""Determine if a server exists.

        Args:
            srv_address (str): Address of server comm.

        Returns:
            bool: True if a server with the provided address exists, False
                otherwise.

        """
        srv_param = parse_address(srv_address)
        if srv_param['port'] is None:
            return False
        return super(ZMQComm, self).server_exists(srv_address)

    @property
    def is_open_direct(self):
        r"""bool: True if the socket is open."""
        with self.socket_lock:
            return (self._openned and not self.socket.closed)

    def is_message(self, flags):
        r"""Poll the socket for a message.

        Args:
            flags (int): ZMQ poll flags.

        Returns:
            bool: True if there is a message matching the flags, False otherwise.

        """
        out = 0
        # with self._closing_thread.lock:
        with self.socket_lock:
            if self.is_open_direct:
                try:
                    out = self.socket.poll(timeout=1, flags=flags)
                except zmq.ZMQError:  # pragma: debug
                    # self.exception('Error polling')
                    pass
        return bool(out)
        
    @property
    def n_msg_direct_recv(self):
        r"""int: Number of messages currently being routed from recv."""
        if self.is_open_direct:
            return int(self.is_message(zmq.POLLIN))
        return 0

    @property
    def n_msg_direct_send(self):
        r"""int: Number of messages currently being routed."""
        if self.is_open_direct and (self.direction == 'send'):
            return (self._n_zmq_sent - self._n_reply_sent)
        return 0

    # @property
    # def is_confirmed_send(self):
    #     r"""bool: True if all sent messages have been confirmed."""
    #     if self.is_open_backlog:
    #         return (self._n_zmq_sent == self._n_reply_sent)
    #     return True  # pragma: debug

    # @property
    # def is_confirmed_recv(self):
    #     r"""bool: True if all received messages have been confirmed."""
    #     if self.is_open_backlog:
    #         return (self._n_zmq_recv == self._n_reply_recv)
    #     return True  # pragma: debug

    @property
    def get_work_comm_kwargs(self):
        r"""dict: Keyword arguments for an existing work comm."""
        out = super(ZMQComm, self).get_work_comm_kwargs
        out['socket_type'] = 'PAIR'
        return out

    @property
    def create_work_comm_kwargs(self):
        r"""dict: Keyword arguments for a new work comm."""
        out = super(ZMQComm, self).create_work_comm_kwargs
        out['socket_type'] = 'PAIR'
        return out
    
    def _send_multipart_worker(self, msg, header, **kwargs):
        r"""Send multipart message to the worker comm identified.

        Args:
            msg (str): Message to be sent.
            header (dict): Message info including work comm address.

        Returns:
            bool: Success or failure of sending the message.

        """
        workcomm = self.get_work_comm(header)
        args = [msg]
        self.sched_task(0, workcomm._send_multipart, args=args, kwargs=kwargs)
        return True

    def _send_direct(self, msg, topic='', identity=None, **kwargs):
        r"""Send a message.

        Args:
            msg (str, bytes): Message to be sent.
            topic (str, optional): Filter that should be sent with the
                message for 'PUB' sockets. Defaults to ''.
            identity (str, optional): Identify of identified worker that
                should be sent for 'ROUTER' sockets. Defaults to
                self.dealer_identity.
            **kwargs: Additional keyword arguments are passed to socket send.

        Returns:
            bool: Success or failure of send.

        """
        if not self.is_open_direct:  # pragma: debug
            self.error("Socket closed")
            return False
        if identity is None:
            identity = self.dealer_identity
        topic = backwards.unicode2bytes(topic)
        identity = backwards.unicode2bytes(identity)
        if self.socket_type_name == 'PUB':
            total_msg = topic + _flag_zmq_filter + msg
        else:
            total_msg = msg
        total_msg = self.check_reply_socket_send(total_msg)
        kwargs.setdefault('flags', zmq.NOBLOCK)
        with self.socket_lock:
            try:
                if self.socket.closed:  # pragma: debug
                    self.error("Socket closed")
                    return False
                self.debug("Sending %d bytes to %s", len(total_msg), self.address)
                if self.socket_type_name == 'ROUTER':
                    self.socket.send(identity, zmq.SNDMORE)
                self.socket.send(total_msg, **kwargs)
                self.debug("Sent %d bytes to %s", len(total_msg), self.address)
                self._n_zmq_sent += 1
            except zmq.ZMQError as e:  # pragma: debug
                if e.errno == zmq.EAGAIN:
                    raise AsyncComm.AsyncTryAgain("Socket not yet available.")
                else:
                    self.special_debug("Socket could not send. (errno=%d)", e.errno)
                    return False
        return True

    def _recv_direct(self, **kwargs):
        r"""Receive a message from the ZMQ socket.

        Args:
            **kwargs: Additional keyword arguments are passed to socket send.

        Returns:
            tuple (bool, obj): Success or failure of receive and received
                message.

        """
        # # Poll until there is a message
        # if timeout is None:
        #     timeout = self.recv_timeout
        # # self.sleep()
        # if timeout is not False:
        #     if not self.is_open_direct:  # pragma: debug
        #         return (False, None)
        #     ret = self.socket.poll(timeout=max(1, 1000.0 * timeout))
        #     if ret == 0:
        #         self.verbose_debug("No messages waiting.")
        #         return (True, self.empty_msg)
        #     flags = zmq.NOBLOCK
        # else:
        #     flags = 0
        flags = zmq.NOBLOCK
        # Receive message
        with self.socket_lock:
            try:
                if self.socket.closed:  # pragma: debug
                    self.error("Socket closed")
                    return (False, self.empty_msg)
                if self.socket_type_name == 'ROUTER':
                    identity = self.socket.recv(flags)
                    self._recv_identities.add(identity)
                kwargs.setdefault('flags', flags)
                total_msg = self.socket.recv(**kwargs)
            except zmq.ZMQError:  # pragma: debug
                self.exception("Error receiving")
                return (False, self.empty_msg)
        self.debug("Recv %d bytes from %s", len(total_msg), self.address)
        # Interpret headers
        total_msg, k = self.check_reply_socket_recv(total_msg)
        if self.socket_type_name == 'SUB':
            topic, msg = total_msg.split(_flag_zmq_filter)
            assert(topic == self.topic_filter)
        else:
            msg = total_msg
        # Confirm receipt
        if k is not None:
            self._n_zmq_recv[k] += 1
        return (True, msg)

    def confirm_send(self, noblock=False):
        r"""Confirm that sent message was received."""
        if noblock:
            if self.is_open and (self._n_zmq_sent != self._n_reply_sent):
                self._n_reply_sent = self._n_zmq_sent
            return True
        if self.is_open and (self._n_zmq_sent != self._n_reply_sent):
            self.verbose_debug("Confirming %d/%d sent messages",
                               self._n_reply_sent, self._n_zmq_sent)
            if self._reply_handshake_send():
                self.debug("Send confirmed (%d/%d)",
                           self._n_reply_sent, self._n_zmq_sent)
                return True
            return False
        return True

    def confirm_recv(self, noblock=False):
        r"""Confirm that message was received."""
        if noblock:
            for k in self.reply_socket_recv.keys():
                if self.is_open and (self._n_zmq_recv[k] != self._n_reply_recv[k]):
                    self._n_reply_recv[k] = self._n_zmq_recv[k]
            return True
        flag = None
        for k in self.reply_socket_recv.keys():
            if self.is_open and (self._n_zmq_recv[k] != self._n_reply_recv[k]):
                self.debug("Confirming %d/%d received messages",
                           self._n_reply_recv[k], self._n_zmq_recv[k])
                if self._reply_handshake_recv(_reply_msg, k):
                    self.debug("Recv confirmed (%d/%d)",
                               self._n_reply_recv[k], self._n_zmq_recv[k])
                    flag = True
                elif flag is None:
                    flag = False
        if flag is None:
            flag = True
        return flag
            
    # def purge(self):
    #     r"""Purge all messages from the comm."""
    #     with self._closing_thread.lock:
    #         # with self._reply_thread.lock:
    #         if self.direction == 'recv':
    #             while self.n_msg_recv > 0:
    #                 msg = self.socket.recv(flags=zmq.NOBLOCK)
    #                 self.check_reply_socket_recv(msg)
    #             for k in self.reply_socket_recv.keys():
    #                 # self._do_reply_recv[k].clear()
    #                 self._n_reply_recv[k] = 0
    #                 self._n_zmq_recv[k] = 0
    #                 # self._n_recv_zmq[k] = 0
    #                 if self.is_open:
    #                     flag = self._reply_handshake_recv(_purge_msg, k)
    #                     assert(flag)
    #             self._do_reply_recv_master.clear()
    #         else:
    #             # Can't purge output on unidirection sockets
    #             self._do_reply_send.clear()
    #             self._n_reply_send = 0
    #             self._n_zmq_sent = 0
    #     super(ZMQComm, self).purge()