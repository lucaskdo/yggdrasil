import uuid
from yggdrasil.drivers.ConnectionDriver import ConnectionDriver


class ServerResponseDriver(ConnectionDriver):
    r"""Class for handling server side RPC type communication.

    Args:
        response_address (str): The address of the channel used to send
            responses to the client response driver.
        comm (str, optional): The comm class that should be used to
            communicate with the server resposne driver. Defaults to
            tools.get_default_comm().
        msg_id (str, optional): ID associate with the request message this
            driver was created to respond to. Defaults to new unique ID.
        **kwargs: Additional keyword arguments are passed to parent class.

    Attributes:
        comm (str): The comm class that should be used to communicate
            with the server driver. Defaults to tools.get_default_comm().
        msg_id (str): ID associate with the request message this driver was
            created to respond to.

    """

    _connection_type = None

    def __init__(self, response_address, comm=None, msg_id=None,
                 request_name=None, **kwargs):
        if msg_id is None:
            msg_id = str(uuid.uuid4())
        response_name = 'ServerResponse.%s' % msg_id
        if request_name is not None:
            response_name = request_name + '.' + response_name
        # Input communicator from client model
        inputs = kwargs.get('inputs', [{}])
        inputs[0]['comm'] = None
        inputs[0]['name'] = 'server_model_response.' + msg_id
        inputs[0]['is_response_server'] = True
        kwargs['inputs'] = inputs
        # Output communicator to client response driver
        outputs = kwargs.get('outputs', [{}])
        outputs[0]['comm'] = comm
        outputs[0]['name'] = response_name
        if response_address is not None:
            outputs[0]['address'] = response_address
        kwargs['outputs'] = outputs
        # Overall keywords
        kwargs['single_use'] = True
        super(ServerResponseDriver, self).__init__(response_name, **kwargs)
        self.comm = comm
        self.msg_id = msg_id
        
    @property
    def model_response_name(self):
        r"""str: The name of the channel used by the server model to send
        responses."""
        return self.icomm.name

    @property
    def model_response_address(self):
        r"""str: The address of the channel used by the server model to send
        responses."""
        return self.icomm.address
    
    @property
    def response_address(self):
        r"""str: The address of the channel used to send responses to the client
        response driver."""
        return self.ocomm.address
