from __future__ import print_function
import sys
from cis_interface.interface.PsiInterface import PsiRpcClient


def fibClient(args):
    
    iterations = int(args[0])
    print('Hello from Python rpcFibCliPar: iterations = %d' % iterations)

    # Create RPC connection with server
    rpc = PsiRpcClient("cli_par_fib", "%d", "%d %d")

    # Send all of the requests to the server
    for i in range(1, iterations + 1):
        print('rpcFibCliPar(P): fib(->%-2d) ::: ' % i)
        ret = rpc.rpcSend(i)
        if not ret:
            print('rpcFibCliPar(P): SEND FAILED')
            sys.exit(-1)

    # Receive responses for all requests that were sent
    for i in range(1, iterations + 1):
        ret, fib = rpc.rpcRecv()
        if not ret:
            print('rpcFibCliPar(P): RECV FAILED')
            break
        print('rpcFibCliPar(P): fib(%2d<-) = %-2d<-' % fib)

    print('Goodbye from Python rpcFibCliPar')
    sys.exit(0)

    
if __name__ == '__main__':
    fibClient(sys.argv[1:])
