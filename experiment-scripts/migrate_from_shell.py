#!/usr/bin/env python
#code taken from https://www.redhat.com/en/blog/container-migration-around-world and partially modified
import socket
import sys
import select
import time
import os
import shutil
import subprocess
import distutils.util
#import rpyc


def error():
    print "Something did not work. Exiting!"
    sys.exit(1)

def prepare(image_path, parent_path):
    try:
        shutil.rmtree(image_path)
    except:
        pass
    try:
        shutil.rmtree(parent_path)
    except:
        pass

def pre_dump(base_path, container):
    old_cwd = os.getcwd()
    os.chdir(base_path)
    cmd = 'time -p runc checkpoint  --pre-dump --image-path parent'
    cmd += ' ' + container
    start = time.time()
    print "Starting checkpointing pre-dump at: %f" % (start) 
    ret = os.system(cmd)
    #end = time.time()
    #print "%s finished after %d second(s) with %d" % (cmd, end - start, ret)
    os.chdir(old_cwd)
    if ret != 0:
        error()

def real_dump(precopy, postcopy):
    old_cwd = os.getcwd()
    os.chdir(base_path)
    cmd = 'time -p runc checkpoint --image-path image --leave-running'
    cmd = 'time -p runc checkpoint --image-path image '
    if precopy:
        cmd += ' --parent-path ../parent'
    if postcopy:
        cmd += ' --lazy-pages'
        cmd += ' --page-server localhost:27'
        try:
            os.unlink('/tmp/postcopy-pipe')
        except:
            pass
        os.mkfifo('/tmp/postcopy-pipe')
        cmd += ' --status-fd /tmp/postcopy-pipe'
    cmd += ' ' + container
    start = time.time()
    print "Starting checkpointing dump at: %f" % (start)
    print cmd
    p = subprocess.Popen(cmd, shell=True)
    if postcopy:
        p_pipe = os.open('/tmp/postcopy-pipe', os.O_RDONLY)
        ret = os.read(p_pipe, 1)
        if ret == '\0':
            print 'Ready for lazy page transfer'
        ret = 0
    else:
        ret = p.wait()

    end = time.time()
    print "%s finished after %.2f second(s) with %d" % (cmd, end - start, ret)
    os.chdir(old_cwd)
    if ret != 0:
        error()

def xfer_pre_dump(parent_path, dest, base_path):
    sys.stdout.write('PRE-DUMP size: ')
    sys.stdout.flush()
    cmd = 'du -hs %s' % parent_path
    ret = os.system(cmd)
    cmd = 'time -p rsync %s --stats %s %s:%s/' % (rsync_opts, parent_path, dest, base_path)
    print "Transferring PRE-DUMP to %s" % dest
    #start = time.time()
    ret = os.system(cmd)
    #end = time.time()
    #print "PRE-DUMP transfer time %s seconds" % (end - start)
    if ret != 0:
        error()

def xfer_final(image_path, dest, base_path):
    sys.stdout.write('DUMP size: ')
    sys.stdout.flush()
    cmd = 'du -hs %s' % image_path
    ret = os.system(cmd)
    cmd = 'time -p rsync %s --stats %s %s:%s/' % (rsync_opts, image_path, dest, base_path)
    print "Transferring DUMP to %s" % dest
    #start = time.time()
    ret = os.system(cmd)
    #end = time.time()
    #print "DUMP transfer time %s seconds" % (end - start)
    if ret != 0:
        error()

def touch(fname):
    open(fname, 'a').close()

# def give_ip(dest):
#     print "Giving floating IP to " + dest
#     touch('/tmp/give_up_master_99')
#     cs = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
#     cs.connect((dest, 18863))
#     cs.send('{ "take_ip" : "/tmp/give_up_master_99" }')
#     os.system('systemctl stop keepalived')
#     cs.close()

def migrate(container, dest, pre, lazy):
    base_path = runc_base + container
    image_path = base_path + "/image"
    parent_path = base_path + "/parent"

    prepare(image_path, parent_path)
    if pre:
        pre_dump(base_path, container)
        xfer_pre_dump(parent_path, dest, base_path)
    real_dump(pre, lazy)
    # give_ip(dest)
    xfer_final(image_path, dest, base_path)

    cs = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    cs.connect((dest, 18863))

    input = [cs,sys.stdin]


    cs.send('{ "restore" : { "path" : "' + base_path + '", "name" : "' + container + '" , "image_path" : "' + image_path + '" , "lazy" : "' + str(lazy) + '" } }')

    while True:
        inputready, outputready, exceptready = select.select(input,[],[], 5)

        if not inputready:
            break

        for s in inputready:
             answer = s.recv(1024)
             print answer

    print "Migrate function in migrate_from_shell is returning"
    return True
    
    
#def remove_directories(container, pre):
 #   base_path = runc_base + container
 #   old_cwd = os.getcwd()
 #   os.chdir(base_path)
 #   cmd = 'rm -rf ./image'
 #   ret = os.system(cmd)
 #   if ret == 0 and pre:
    #    cmd = 'rm -rf ./parent'
    #    ret = os.system(cmd)
 #   os.chdir(old_cwd)
 #   if ret != 0:
    #    error()
    

if __name__ == '__main__':

    runc_base = "/runc/containers/"

    lazy = False
    pre = False

    #if len(sys.argv) < 3:
        # print "Usage: " + sys.argv[0] + " [container id] [destination] [pre-copy] [post-copy]"
        # sys.exit(1)
        #from rpyc.utils.server import ThreadedServer
        #server = ThreadedServer(MigrationTrigger, port=18862)
        #server.start()

    container = sys.argv[1]
    dest = sys.argv[2]
    if len(sys.argv) > 3:
        pre = distutils.util.strtobool(sys.argv[3])
    if len(sys.argv) > 4:
        lazy = distutils.util.strtobool(sys.argv[4])

    base_path = runc_base + container
    image_path = base_path + "/image"
    parent_path = base_path + "/parent"

    rsync_opts = "-ha"

    migrate(container, dest, pre, lazy)
    #remove_directories(container, pre)

    print "Exiting migrate_from_shell"
