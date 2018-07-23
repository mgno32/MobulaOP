import os
import sys
import functools
import yaml
from easydict import EasyDict as edict
import threading
import multiprocessing
import hashlib
import re
try:
    import Queue
except ImportError:
    import queue as Queue

INC_PATHS = ['./']

# Load Config File
with open('./config.yaml') as fin:
    config = edict(yaml.load(fin))

def save_code_hash(obj, fname):
    with open(fname, 'w') as f:
        for k, v in obj.items():
            f.write('%s %s\n' % (k, v))

def load_code_hash(fname):
    data = dict()
    try:
        with open(fname, 'r') as f:
            for line in f:
                sp = line.split(' ')
                data[sp[0]] = sp[1].strip()
    except:
        pass
    return data

code_hash = dict()
code_hash_filename = os.path.join(config.BUILD_PATH, 'code.hash')
if os.path.exists(code_hash_filename):
    code_hash = load_code_hash(code_hash_filename)
code_hash_updated = False

def save_dependant(obj, fname):
    with open(fname, 'w') as f:
        for k, v in obj.items():
            if len(v) > 0:
                s = '{} {}\n'.format(k, ','.join(v))
                f.write(s)

def load_dependant(fname):
    data = dict()
    try:
        with open(fname, 'r') as f:
            for line in f:
                sp = line.strip().split(' ')
                data[sp[0]] = sp[1].split(',')
    except:
        pass
    return data

dependant = dict()
dependant_filename = os.path.join(config.BUILD_PATH, 'code.dependant')
if os.path.exists(dependant_filename):
    dependant = load_dependant(dependant_filename)
dependant_updated = False

def build_exit():
    if code_hash_updated:
        save_code_hash(code_hash, code_hash_filename)
    if dependant_updated:
        save_dependant(dependant, dependant_filename)

class Flags:
    def __init__(self, s = ''):
        self.flags = s
    def add_definition(self, key, value):
        if isinstance(value, bool):
            value = int(value)
        self.flags += ' -D %s=%s' % (key, str(value))
        return self
    def add_string(self, s):
        self.flags += ' %s' % str(s)
        return self
    def __str__(self):
        return self.flags

INCLUDE_FILE_REG = re.compile('^\s*#include\s*(?:"|<)\s*(.*?)\s*(?:"|>)\s*')
def get_include_file(fname):
    include_str = '#include'
    res = []
    for line in open(fname):
        u = INCLUDE_FILE_REG.search(line)
        if u is not None:
            inc_fname = u.groups()[0]
            res.append(inc_fname)
    return res

def wildcard(path, ext):
    if isinstance(path, list):
        res = []
        for p in path:
            res.extend(wildcard(p, ext))
        return res
    res = []
    for name in os.listdir(path):
        e = os.path.splitext(name)[1]
        if e == '.' + ext:
            res.append(os.path.join(path, name))
    return res

def change_ext(lst, origin, target):
    res = []
    for name in lst:
        sp = os.path.splitext(name)
        if sp[1] == '.' + origin:
            res.append(sp[0] + '.' + target)
        else:
            res.append(name)
    return res

def run_command(command):
    print (command)
    os.system(command)

def mkdir(dir_name):
    if not os.path.exists(dir_name):
        print ('mkdir -p %s' % dir_name)
        os.makedirs(dir_name)

def rmdir(dir_name):
    if os.path.exists(dir_name):
        command = 'rm -rf %s' % dir_name
        run_command(command)

def get_file_hash(fname):
    return str(os.path.getmtime(fname))
    m = hashlib.md5()
    with open(fname, 'rb') as f:
        while True:
            data = f.read(1024)
            if not data:
                break
            m.update(data)
    return m.hexdigest()[:8]

def file_changed(fname):
    global code_hash_updated
    new_hash = get_file_hash(fname)
    if fname not in code_hash or new_hash != code_hash[fname]:
        code_hash_updated = True
        code_hash[fname] = new_hash
        return True
    return False

def find_include(inc):
    for path in INC_PATHS:
        fname = os.path.relpath(os.path.join(path, inc))
        if os.path.exists(fname):
            return fname
    return None

def update_dependant(fname):
    global dependant_updated
    dependant_updated = True
    inc_files = get_include_file(fname)
    res = []
    for inc in inc_files:
        inc_fname = find_include(inc)
        if inc_fname is not None:
            res.append(inc_fname)
    dependant[fname] = res

def dependant_changed(fname):
    if fname not in dependant:
        update_dependant(fname)
    includes = dependant[fname]
    changed = False
    for inc in includes:
        inc_fname = find_include(inc)
        if inc_fname is None or not file_is_latest(inc_fname):
            changed = True
    return changed

FILE_CHECK_LIST = dict()

def file_is_latest(source):
    if source in FILE_CHECK_LIST:
        t = FILE_CHECK_LIST[source]
        assert t is not None, RuntimeError("Error: Cycle Reference {}".format(source))
        return t
    FILE_CHECK_LIST[source] = None
    latest = True
    if file_changed(source):
        latest = False
        update_dependant(source)
    if dependant_changed(source):
        latest = False
    FILE_CHECK_LIST[source] = latest
    return latest

def run_command_parallel(commands):
    command_queue = Queue.Queue()
    for c in commands:
        command_queue.put(c)
    max_worker_num = min(config.MAX_BUILDING_WORKER_NUM, len(commands))
    for _ in range(max_worker_num):
        command_queue.put(None)
    def worker(command_queue):
        while not command_queue.empty():
            e = command_queue.get()
            if e is None:
                break
            run_command(e)
    workers = [threading.Thread(target = worker, args = (command_queue,)) for _ in range(max_worker_num)]
    for w in workers:
        w.daemon = True
    for w in workers:
        w.start()
    for w in workers:
        w.join()

def add_path(path, files):
    return list(map(lambda x : os.path.join(path, x), files))