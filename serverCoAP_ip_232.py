from coapthon.server.coap import CoAP
from coapthon.exampleresources import BasicResource
from coapthon.resources.resource import Resource
import paramiko


def ssh_command(mtype:int, dest_addr:str, src_addr:str) -> None:

    client_ssh = paramiko.SSHClient()
    client_ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client_ssh.connect(src_addr, username='ubuntu', password='tesiconforti')

    command = "sudo python master/migrate_from_shell.py python_bundle " + dest_addr
    if(mtype == 0):
        command = command + " false false"  #cold migration
    elif(mtype == 1):
        command = command + " true false"   #pre-copy migration
    elif(mtype == 2):
        command = command + " false true"   #post-copy migration
    elif(mtype == 3):
        command = command + " true true"    #hybrid migration

    stdin, stdout, stderr = client_ssh.exec_command(command)

    #time.sleep(0.1) #Added in order to resolve an error of paramiko library

    for line in stdout:
        print (line.strip('\n'))

    for line_err in stderr:
        print (line_err.strip('\n'))

    client_ssh.close()


class BasicResource(Resource):
    def __init__(self, name="BasicResource", coap_server=None):
        super(BasicResource, self).__init__(name, coap_server, visible=True,observable=True, allow_children=True)
        self.payload = "Basic Resource"

    def render_GET(self, request):
        return self

    def render_PUT(self, request):
        info = request.payload
        info = info.split(",")
        ssh_command(int(info[0]), info[1], info[2])
        self.payload = "OK"
        return self

    def render_POST(self, request):
        res = BasicResource()
        res.location_query = request.uri_query
        res.payload = request.payload
        return res

    def render_DELETE(self, request):
        return True


class CoAPServer(CoAP):
    def __init__(self, host, port):
        CoAP.__init__(self, (host, port))
        self.add_resource('basic/', BasicResource())

def main():
    server = CoAPServer("172.16.4.232", 5683)
    try:
        server.listen(10)
    except KeyboardInterrupt:
        print("Server Shutdown")
        server.close()
        print("Exiting...")

if __name__ == '__main__':
    main()
