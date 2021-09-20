from coapthon.server.coap import CoAP
from coapthon.exampleresources import BasicResource
from coapthon.resources.resource import Resource
import os


def run_command(mtype:int, dest_addr:str) -> None:

    command = "python /home/ubuntu/master/migrate_from_shell.py python_bundle " + dest_addr
    if(mtype == 0):
        command = command + " false false"  #cold migration
    elif(mtype == 1):
        command = command + " true false"   #pre-copy migration
    elif(mtype == 2):
        command = command + " false true"   #post-copy migration
    elif(mtype == 3):
        command = command + " true true"    #hybrid migration

    os.system(command)


class BasicResource(Resource):
    def __init__(self, name="BasicResource", coap_server=None):
        super(BasicResource, self).__init__(name, coap_server, visible=True,observable=True, allow_children=True)
        self.payload = "Basic Resource"

    def render_GET(self, request):
        return self

    def render_PUT(self, request):
        info = request.payload
        info = info.split(",")
        run_command(int(info[0]), info[1])
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
    server = CoAPServer("172.16.4.4", 5683)
    try:
        server.listen(10)
    except KeyboardInterrupt:
        print("Server Shutdown")
        server.close()
        print("Exiting...")

if __name__ == '__main__':
    main()