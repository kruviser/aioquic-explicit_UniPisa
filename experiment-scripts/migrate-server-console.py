#!/usr/bin/env python
#code taken from https://www.redhat.com/en/blog/container-migration-around-world and partially modified
import socket
import sys
from thread import *
import json
import os
import distutils.util
import subprocess
#import dns.update
#import dns.query
#import dns.tsigkeyring

def migrate_server(app_using_tcp):
    HOST = ''   # Symbolic name meaning all available interfaces
    PORT = 18863 # Arbitrary non-privileged port 8888

    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    print 'Socket created'

    #Bind socket to local host and port
    try:
        s.bind((HOST, PORT))
    except socket.error as msg:
        print 'Bind failed. Error Code : ' + str(msg[0]) + ' Message ' + msg[1]
        sys.exit()

    print 'Socket bind complete'

    #Start listening on socket
    s.listen(10)
    print 'Socket now listening'

    #Function for handling connections. This will be used to create threads
    def clientthread(conn, addr, app_using_tcp):
        #Sending message to connected client
        
        #infinite loop so that function do not terminate and thread do not end.
        while True:

            reply = ""
            #Receiving from client
            data = conn.recv(1024)
            if not data:
                break
            if data == 'exit':
                break

            try:
                msg = json.loads(data)
                if 'restore' in msg:

                    os.system('criu -V')

                    try:
                        lazy = bool(distutils.util.strtobool(msg['restore']['lazy']))
                    except:
                        lazy = False

                    old_cwd = os.getcwd()
                    os.chdir(msg['restore']['path'])
                    cmd = 'time -p runc restore --console-socket ' + msg['restore']['path']
                    cmd += '/console.sock -d --image-path ' + msg['restore']['image_path']
                    cmd += ' --work-path ' + msg['restore']['image_path']
                    if lazy:
                            cmd += ' --lazy-pages'
                    cmd += ' ' + msg['restore']['name']
                    print "Running " +  cmd
                    p = subprocess.Popen(cmd, shell=True)
                    if lazy:
                        cmd = "criu lazy-pages --page-server --address " + addr
                        cmd += " --port 27 -vv -D "
                        cmd += msg['restore']['image_path']
                        cmd += " -W "
                        cmd += msg['restore']['image_path']
                        print "Running lazy-pages server: " + cmd
                        lp = subprocess.Popen(cmd, shell=True)
                    ret = p.wait()
                    if ret == 0:
                        reply = "runc restored %s successfully" % msg['restore']['name']
                    else:
                        reply = "runc failed(%d)" % ret
                    os.chdir(old_cwd)
                else:
                    print "Unkown request : " + msg
            except:
                continue
            
            print reply

            #update the DNS server with the new IP address of the container
            #this is done only in case of app_using_tcp = True
            #if QUIC is used instead, this is not done
            #if app_using_tcp:
                #print("Starting update of DNS")
                #os.system("python3 /home/oem/master/dnsupdater.py")
                #keyring = dns.tsigkeyring.from_text({
                 #   'mycompanion.com.': 'OlOAxkefYKheCw8+rm92jw=='
                #})

                #update = dns.update.Update('mycompanion.com', keyring=keyring, keyalgorithm='hmac-md5.sig-alg.reg.int')
                #update.replace('myservice', 5, 'A', '192.168.3.1')
                #response = dns.query.tcp(update, '192.168.1.53')
                #print(str(response))

            conn.sendall(reply)

        #came out of loop
        conn.close()


    #now keep talking with the client
    while 1:
        #wait to accept a connection - blocking call
        conn, addr = s.accept()
        print 'Connected with ' + addr[0] + ':' + str(addr[1])

        #start new thread takes 1st argument as a function name to be run, second is the tuple of arguments to the function.
        start_new_thread(clientthread ,(conn, str(addr[0]), app_using_tcp))

    s.close()

if __name__ == '__main__':
    
    #app_using_tcp is a boolean that indicates whether (True) or not (False) the client-server application is using TCP at transport layer
    #this is used to decide if DNS server needs to be updated with the new IP address of the container
    app_using_tcp = sys.argv[1]

    migrate_server(app_using_tcp)
