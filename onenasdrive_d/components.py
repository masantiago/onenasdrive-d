# -*- coding: utf-8 -*-

import sys
import time
import re
import gc
import subprocess
import threading
import Queue
import os
from config import *
from calendar import timegm
from dateutil import parser
from onedrive import api_v5
import errno
import shutil

API = None
CONFIG_FILE = None

TASK_QUEUE = Queue.Queue()
SCANNER_QUEUE = Queue.Queue()
SCANNER_SEMAPHORE = threading.BoundedSemaphore(value = NUM_OF_SCANNERS)
EVENT_STOP = threading.Event()

# rename files that have same name in lowecase
# and return a dictionary of the new file names
def resolve_CaseConflict(path):
	_ent_dict = {}
	_ent_list = []
	ents = os.listdir(path)
	path += "/"
	for item in ents:
		item_l = item.lower()
		if item_l in _ent_dict:
			# case conflict
			_ent_dict[item_l] += 1
			count = _ent_dict[item_l]
			ext_dot_pos = item.rfind(".")
			if ext_dot_pos == -1:
				os.rename(path + item, path + item + " (CONFLICT_" + str(count) + ")")
				item = item + " (CONFLICT_" + str(count) + ")"
			else:
				item_new = item[0:ext_dot_pos:] + " (CONFLICT_" + str(count) + ")" + item[ext_dot_pos:len(item)]
				os.rename(path + item, path + item_new)
			item_l = item.lower()
		_ent_dict[item_l] = 0
		_ent_list.append(item)
	del _ent_dict
	return _ent_list

class Task():
	def __init__(self, type, p1, p2, timeStamp = None):
		self.type = type
		self.p1 = p1 # mostly used as a local path
		self.p2 = p2 # mostly used as a remote path
		if timeStamp is not None:
			self.timeStamp = timeStamp	# time, etc.

	def debug(self):
		return "Task(" + self.type + ", " + self.p1 + ", " + self.p2 + ")"

class TaskWorker(threading.Thread):

	def __init__(self):
		threading.Thread.__init__(self)
		self.daemon = True
		log.info(self.getName() + " (worker): initiated")

	def getArgs(self, t):
		return {
			"mv": ["mv", t.p1, t.p2],
			"mkdir": ["mkdir", t.p2],	# mkdir path NOT RECURSIVE!
			"get": ["get", t.p2, t.p1],	# get remote_file local_path
			"put": ["put", t.p1, t.p2],	# put local_file remote_dir
			"cp": ["cp", t.p1, t.p2],	# cp file folder
			"rm": ["rm", t.p2]
		}[t.type]

	def getMessage(self, t):
		pass

	def consume(self, t):
		args = self.getArgs(t)
		args = [arg.encode('utf-8') for arg in args]
		subp = subprocess.Popen(['onedrive-cli'] + ["-c", CONFIG_FILE] + args, stdout=subprocess.PIPE)		
		ret = subp.communicate()

		# post-work
		if t.type == "get":
			old_mtime = os.stat(t.p1).st_mtime
			new_mtime = timegm(parser.parse(t.timeStamp).utctimetuple())
			os.utime(t.p1, (new_mtime, new_mtime))
			new_old_mtime = os.stat(t.p1).st_mtime
			log.info(t.p1 + " Old_mtime is " + str(old_mtime) + " and new_mtime is " + str(new_mtime) + " and is changed to " + str(new_old_mtime))
		elif t.type == "mkdir" and t.p1 != "":
			# upload the local dir to remote
			# correspond to scanner's post_merge
			_ent_list = resolve_CaseConflict(t.p1)
			for entry in _ent_list:
				if EXCLUDE != "" and re.match(EXCLUDE, entry):
					log.info(t.p1 + "/" + entry + " is excluded by worker.")
				elif os.path.isfile(t.p1 + "/" + entry):
					TASK_QUEUE.put(Task("put", t.p1 + "/" + entry, t.p2 + "/" + entry))
				else:	# a dir
					TASK_QUEUE.put(Task("mkdir", t.p1 + "/" + entry, t.p2 + "/" + entry))

		if ret[0] is not None and ret[0] != "":
			log.info("subprocess stdout: " + ret[0])
		if ret[1] is not None and ret[0] != "":
			log.info("subprocess stderr: " + ret[1])
		log.info("Executed task: " + t.debug())

		del t

	def run(self):
		while True:
			if TASK_QUEUE.empty():
				time.sleep(WORKER_SLEEP_INTERVAL)
			else:
				task = TASK_QUEUE.get()
				self.consume(task)
				del task
				TASK_QUEUE.task_done()

# DirScanner represents either a file entry or a dir entry in the OneDrive repository
# it uses a single thread to process a directory entry
class DirScanner(threading.Thread):
	def __init__(self, localPath, remotePath):
		threading.Thread.__init__(self)
		SCANNER_QUEUE.put(self)
		self.daemon = True
		self._localPath = localPath.encode(sys.getfilesystemencoding())
		self._remotePath = remotePath
		self._raw_log = None
		log.info(self.getName() + " (scanner): initiated")

	def ls(self):
		SCANNER_SEMAPHORE.acquire()
		log.info("Start scanning dir " + self._remotePath + " (\"" + self._localPath + "\")")
		try:
			self._raw_log = list(API.listdir(API.resolve_path(self._remotePath)))
		except api_v5.DoesNotExists as e:
			log.error("Remote path \"" + self._remotePath + "\" does not exist.\n({0}".format(e.message))
		except api_v5.AuthenticationError as e:
			log.error("Authentication failed.\n({0}".format(e.message))
		except (api_v5.OneDriveInteractionError, api_v5.ProtocolError):
			log.error("OneDrive API error.")
			raise
		finally:
			SCANNER_SEMAPHORE.release()

	def run(self):
		try:
			self.ls()
			self.pre_merge()
			self.merge()
			self.post_merge()
		except:
			log.error("Operation aborted")

	def pre_merge(self):
		# if remote repo has a dir that does not exist locally
		# make it and start merging
		self._ent_list = []
		if not os.path.exists(self._localPath):
			try:
				os.mkdir(self._localPath)
			except OSError as exc:
					if exc.errno == errno.EEXIST and os.path.isdir(self._localPath):
						pass
		else:
			self._ent_list = resolve_CaseConflict(self._localPath)

	# recursively merge the remote files and dirs into local repo
	def merge(self):
		if self._raw_log is not None and self._raw_log != []:
			for entry in self._raw_log:
				if entry["name"] is None:
					continue
				if EXCLUDE != "" and re.match(EXCLUDE, entry["name"]):
					log.info("Remote file " + self._remotePath + "/" + entry["name"] + " is excluded.")
					continue
				self.checkout(entry)

	# checkout one entry, either a dir or a file, from the log
	def checkout(self, entry):
		localPath = (self._localPath + "/" + entry["name"]).encode(sys.getfilesystemencoding())

		isExistent = os.path.exists(localPath)
		if isExistent:
			del self._ent_list[self._ent_list.index(entry["name"])]

		if entry["type"] in "file|photo|audio|video":
			if isExistent:
				# assert for now
				assert os.path.isfile(localPath)
				local_mtime = os.stat(localPath).st_mtime
				remote_mtime = timegm(parser.parse(entry["client_updated_time"]).utctimetuple())

				if local_mtime == remote_mtime:
					log.debug(localPath + " wasn't changed.")
					return
				elif local_mtime > remote_mtime:
					log.info("Local file \"" + self._localPath + "/" + entry["name"] + "\" is newer.")
					# Remote is preferential
					os.remove(localPath)
					TASK_QUEUE.put(Task("get", localPath, self._remotePath + "/" + entry["name"], entry["client_updated_time"]))

				else:
					log.info("Local file \"" + self._localPath + "/" + entry["name"] + "\" is older.")
					# Remote is preferential
					os.remove(localPath)
					TASK_QUEUE.put(Task("get", localPath, self._remotePath + "/" + entry["name"], entry["client_updated_time"]))

			else:
				# if not existent, get the file to local repo
				TASK_QUEUE.put(Task("get", localPath, self._remotePath + "/" + entry["name"], entry["client_updated_time"]))
		else:
			DirScanner(localPath, self._remotePath + "/" + entry["name"]).start()

	# process untouched files during merge
	def post_merge(self):
		# there is untouched item in current dir
		if self._ent_list:
			log.info("The following items are untouched yet:\n" + str(self._ent_list))

			for entry in self._ent_list:
				# Remote is preferential. Local is deleted.
				if EXCLUDE != "" and re.match(EXCLUDE, entry):
					log.info(entry + " is a pattern that is excluded.")
				elif os.path.isfile(self._localPath + "/" + entry):
					log.info(self._localPath + "/" + entry + " is deleted.")
					os.remove(self._localPath + "/" + entry)
				else:	# a dir
					log.info(self._localPath + "/" + entry + " is deleted.")
					shutil.rmtree(self._localPath + "/" + entry)

		log.info("Thread finished.")

class Waiter(threading.Thread):

	def __init__(self):
		threading.Thread.__init__(self)
		self.daemon = True
		log.info(self.getName() + " (waiter): initiated")

	def run(self):
		while not SCANNER_QUEUE.empty():
			t = SCANNER_QUEUE.get()
			SCANNER_QUEUE.task_done()
			t.join()
			del t

		TASK_QUEUE.join()
		gc.collect()

		log.info("Thread finished.")
		EVENT_STOP.set()
