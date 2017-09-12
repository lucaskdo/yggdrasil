
#include "PsiInterface.h"
#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>
#include <signal.h>


int main(int argc, char *argv[]) {

  int iterations = atoi(argv[1]);
  printf("Hello from C rpcFibCliPar: iterations = %d\n", iterations);
  
  // Create RPC connection with server 
  psiRpc_t rpc = psiRpcClient("cli_par_fib", "%d", "%d %d");
  
  // Send all of the requests to the server
  int ret;
  for (int i = 1; i <= iterations; i++) {
    printf("rpcFibCliPar(C): fib(->%-2d) ::: \n", i);
    ret = rpcSend(rpc, i);
    if (ret != 0) {
      printf("rpcFibCliPar(C): SEND FAILED\n");
      exit(-1);
    }
  }

  // Receive responses for all requests that were sent
  int fib = -1;
  int fibNo = -1;
  for (int i = 1; i <= iterations; i++) {
    ret = rpcRecv(rpc, &fibNo, &fib);
    if (ret < 0) {
      printf("rpcFibCliPar(C): RECV FAILED\n");
      exit(-1);
    }
    printf("rpcFibCliPar(C):  fib(%2d<-) = %-2d<-\n", fibNo, fib);
  }

  printf("Goodbye from C rpcFibCliPar\n");
  exit(0);
    
}

