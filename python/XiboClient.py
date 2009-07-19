#!/usr/bin/python
# -*- coding: utf-8 -*-

from libavg import avg, anim
from SOAPpy import WSDL
import SOAPpy.Types
import SOAPpy.Errors
import xml.parsers.expat
from xml.dom import minidom
import time
import uuid
import hashlib
import Queue
import ConfigParser
import gettext
import os
import re
import time
import sys
import socket
from collections import defaultdict
from threading import Thread, Semaphore

version = "1.1.0"
#TODO: Change to 2!
schemaVersion = 1

#### Abstract Classes
class XiboLog:
    "Abstract Class - Interface for Loggers"
    level=0
    def __init__(self,level): abstract
    def log(self,level,category,message): abstract
    def stat(self,type, message, layoutID, scheduleID, mediaID): abstract

class XiboScheduler(Thread):
    "Abstract Class - Interface for Schedulers"
    def run(self): abstract
    def nextLayout(self): abstract
    def hasNext(self): abstract
#### Finish Abstract Classes

#### Log Classes
class XiboLogFile(XiboLog):
    "Xibo Logger - to file"
    def __init__(self,level):
        pass
        
    def log(self,level, category, message):
        pass
    
    def stat(self,type, message, layoutID, scheduleID, mediaID):
        pass

class XiboLogScreen(XiboLog):
    "Xibo Logger - to screen"
    def __init__(self,level):
        # Make sure level is sane
        if level == "" or int(level) < 0:
            level=0
        self.level = int(level)
        
        self.log(2,"info",_("XiboLogScreen logger started at level ") + str(level))
    
    def log(self, severity, category, message):
        if self.level >= severity:
            print "LOG: " + str(severity) + " " + category + " " + message
    
    def stat(self, type, message, layoutID, scheduleID, mediaID=""):
        print "STAT: " + type + " " + message + " " + str(layoutID) + " " + str(scheduleID) + " " + str(mediaID)

class XiboLogXmds(XiboLog):
    def log(self,level, category, message):
        pass
    
    def stat(self,type, message, layoutID, scheduleID, mediaID):
        pass
#### Finish Log Classes

#### Download Manager
class XiboFile(object):
    def __init__(self,path):
	self.__path = path
	self.md5 = ""
	self.checkTime = 1
	self.update()

    def update(self):
	# Generate MD5
	m = hashlib.md5()
    	try:
            fd = open(self.__path,"rb")
    	except IOError:
            return False
        content = fd.readlines()
        fd.close()
	for eachLine in content:
            m.update(eachLine)
    	self.md5 = m.hexdigest()

	self.checkTime = time.time()
	return True

    def isExpired(self):
	if self.checkTime < time.time() + 3600:
	    return False
	return True
        
class XiboDownloadManager(Thread):
    def __init__(self,xmds):
        log.log(3,"info",_("New XiboDownloadManager instance created."))
        Thread.__init__(self)
	self.xmds = xmds
	self.running = True
	self.dlQueue = Queue.Queue(0)

	# Store a dictionary of XiboFile objects so we know how recently
	# we last checked a file was present and correct.
	self.md5Cache = defaultdict(XiboFile)
	
	# Store a dictionary of XiboDownloadThread objects so we know
	# which files are downloading and how many download slots
	# there are free
	self.runningDownloads = defaultdict(XiboDownloadThread)

	# How many XiboDownloadThreads should run at once
	self.maxDownloads = 5
    
    def run(self):
        log.log(2,"info",_("New XiboDownloadManager instance started."))
	while (self.running):
	    self.interval = 300

	    # Find out how long we should wait between updates.
	    try:
	         self.interval = int(config.get('Main','xmdsUpdateInterval'))
	    except:
		# self.interval has been set to a sensible default in this case.
 	        log.log(0,"warning",_("No XMDS Update Interval specified in your configuration"))
	        log.log(0,"warning",_("Please check your xmdsUpdateInterval configuration option"))
		log.log(0,"warning",_("A default value has been used:") + " " + str(self.interval) + " " + _("seconds"))

	    # Go through the list comparing required files to files we already have.
	    # If a file differs, queue it for download
	    reqFiles = '<files></files>'
	    try:
		reqFiles = self.xmds.RequiredFiles()
		log.log(5,"info",_("XiboDownloadManager: XMDS RequiredFiles() returned ") + str(reqFiles))
	    except XMDSException:
		log.log(0,"warning",_("XMDS RequiredFiles threw an exception"))

	    self.doc = None
	    # Pull apart the retuned XML
	    try:
		self.doc = minidom.parseString(reqFiles)
	    except:
		log.log(0,"warning",_("XMDS RequiredFiles returned invalid XML"))

	    # Find the layout node and store it
	    if self.doc != None:
		for e in self.doc.childNodes:
		    if e.nodeType == e.ELEMENT_NODE and e.localName == "files":
			# e is a files node.
			#log.log(5,"info","Files Node found!")
			for f in e.childNodes:
			    # It's a Media node
			    if f.nodeType == f.ELEMENT_NODE and f.localName == "file" and str(f.attributes['type'].value) == "media":
				#log.log(5,"info","Media File Node found!")
				# Does the file exist? Is it the right size?
				try:
				    tmpPath = config.get('Main','libraryDir') + os.sep + str(f.attributes['path'].value)
				    tmpSize = int(f.attributes['size'].value)
				    tmpHash = str(f.attributes['md5'].value)
				    tmpType = str(f.attributes['type'].value)
				    if os.path.isfile(tmpPath) and os.path.getsize(tmpPath) == tmpSize:
					# File exists and is the right size
					# See if we checksummed it recently
					if tmpPath in self.md5Cache:
					    # Check if the md5 cache is old for this file
					    if self.md5Cache[tmpPath].isExpired():
						# Update the cache if it is
						self.md5Cache[tmpPath].update()
						
					    if self.md5Cache[tmpPath].md5 != tmpHash:
						# The hashes don't match.
						# Queue for download.
						log.log(2,"warning",_("File exists and is the correct size, but the checksum is incorrect. Queueing for download. ") + tmpPath)
						self.dlQueue.put((tmpType,tmpPath,tmpSize,tmpHash),False)						
					else:
					    tmpFile = XiboFile(tmpPath)
					    self.md5Cache[tmpPath] = tmpFile
					    if tmpFile.md5 != tmpHash:
						# The hashes don't match.
						# Queue for download.
						log.log(2,"warning",_("File exists and is the correct size, but the checksum is incorrect. Queueing for download. ") + tmpPath)
						self.dlQueue.put((tmpType,tmpPath,tmpSize,tmpHash),False)
				    else:
					# Queue the file for download later.
					log.log(3,"info",_("File does not exist. Queueing for download. ") + tmpPath)
					self.dlQueue.put((tmpType,tmpPath,tmpSize,tmpHash),False)
				except:
				    # TODO: Blacklist the media item.
				    log.log(0,"error",_("RequiredFiles XML error: File type=media has no path attribute or no size attribute. Blacklisting."))

			    # It's a Layout node.
			    if f.nodeType == f.ELEMENT_NODE and f.localName == "file" and str(f.attributes['type'].value) == "layout":
				try:
				    tmpPath = config.get('Main','libraryDir') + os.sep + str(f.attributes['path'].value) + '.xlf'
				    tmpHash = str(f.attributes['md5'].value)
				    tmpType = str(f.attributes['type'].value)
				    if os.path.isfile(tmpPath):
					# File exists
					# See if we checksummed it recently
					if tmpPath in self.md5Cache:
					    # Check if the md5 cache is old for this file
					    if self.md5Cache[tmpPath].isExpired():
						# Update the cache if it is
						self.md5Cache[tmpPath].update()
						
					    if self.md5Cache[tmpPath].md5 != tmpHash:
						# The hashes don't match.
						# Queue for download.
						log.log(2,"warning",_("File exists and is the correct size, but the checksum is incorrect. Queueing for download. ") + tmpPath)
						self.dlQueue.put((tmpType,tmpPath,0,tmpHash),False)						
					else:
					    tmpFile = XiboFile(tmpPath)
					    self.md5Cache[tmpPath] = tmpFile
					    if tmpFile.md5 != tmpHash:
						# The hashes don't match.
						# Queue for download.
						log.log(2,"warning",_("File exists and is the correct size, but the checksum is incorrect. Queueing for download. ") + tmpPath)
						self.dlQueue.put((tmpType,tmpPath,0,tmpHash),False)
				    else:
					# Queue the file for download later.
					log.log(3,"info",_("File does not exist. Queueing for download. ") + tmpPath)
					self.dlQueue.put((tmpType,tmpPath,0,tmpHash),False)
				except:
				    # TODO: Blacklist the media item.
				    log.log(0,"error",_("RequiredFiles XML error: File type=layout has no path attribute or no hash attribute. Blacklisting."))

			    # It's a Blacklist node
			    if f.nodeType == f.ELEMENT_NODE and f.localName == "file" and str(f.attributes['type'].value) == "blacklist":
				#log.log(5,"info","Blacklist File Node found!")
				# TODO: Do something with the blacklist
				pass
	    # End If self.doc != None

	    # Loop over the queue and download as required
	    try:
		# Throttle this to a maximum number of dl threads.
		while True:
		    tmpType, tmpPath, tmpSize, tmpHash = self.dlQueue.get(False)
		
		    # Check if the file is downloading already
		    if not tmpPath in self.runningDownloads:
		    	# Make a download thread and actually download the file.
			# Add the running thread to the self.runningDownloads dictionary
			self.runningDownloads[tmpPath] = XiboDownloadThread(self,tmpType,tmpPath,tmpSize,tmpHash)
			self.runningDownloads[tmpPath].start()

		    while len(self.runningDownloads) >= (self.maxDownloads - 1):
			# There are no download thread slots free
			# Sleep for 5 seconds and try again.
			log.log(3,"info",_("All download slots filled. Waiting for a download slot to become free"))
			time.sleep(5)
		    # End While

	    except Queue.Empty:
		# Used to exit the above while once all items are downloaded.
		pass

	    # Loop over the MD5 hash cache and remove any entries older than 1 hour
	    # TODO: Throws an exception "ValueError: too many values to unpack"
	    for tmpPath, tmpFile in self.md5Cache.iteritems():
		if tmpFile.isExpired():
		    del self.md5Cache[tmpPath]
	    # End Loop
		
	    log.log(3,"info",_("XiboDownloadManager: Sleeping") + " " + str(self.interval) + " " + _("seconds"))
	    time.sleep(self.interval)
	# End While

    def dlThreadCompleteNotify(self,tmpPath):
	# Download thread completed. Log and remove from
	# self.runningDownloads
	log.log(3,"info",_("Download thread completed for ") + tmpPath)
	del self.runningDownloads[tmpPath]

class XiboDownloadThread(Thread):
    def __init__(self,parent,tmpType,tmpPath,tmpSize,tmpHash):
        Thread.__init__(self)
	self.tmpType = tmpType
	self.tmpPath = tmpPath
	self.tmpSize = tmpSize
	self.tmpHash = tmpHash
	self.parent = parent
	self.offset = 0
	self.chunk = 512000

    def run(self):
	# Manage downloading the appropriate type of file:
	if self.tmpType == "media":
	    self.downloadMedia()
	elif self.tmpType == "layout":
	    self.downloadLayout()

	# Let the DownloadManager know we're complete
	self.parent.dlThreadCompleteNotify(self.tmpPath)

    def downloadMedia(self):
	# Actually download the Media file
	finished = False
	tries = 0

	if os.path.isfile(self.tmpPath):
	    try:
	        os.remove(self.tmpPath)
	    except:
		log.log(0,"error",_("Unable to delete file: ") + self.tmpPath)
		return

	append = True

	fh = None
	try:
	    fh = open(self.tmpPath, 'wb')
	except:
	    log.log(0,"error",_("Unable to write file: ") + self.tmpPath)
	    return

        while tries < 5 and not finished:
	    tries = tries + 1
	    while self.offset < self.tmpSize:
		# If downloading this chunk will complete the file
		# work out exactly how much to download this time
		if self.offset + self.chunk > self.tmpSize:
		    self.chunk = self.tmpSize - self.offset

		try:
		     # Fix path attribute so it's just the filename (minus the client path)
		     shortPath = self.tmpPath.replace(config.get('Main','libraryDir') + os.sep,'',1)
		     response = self.parent.xmds.GetFile(shortPath,self.tmpType,self.offset,self.chunk)
		     fh.write(response)
		     fh.flush()
		     self.offset = self.offset + self.chunk
		except RuntimeError:
		     # TODO: Do something sensible
		     pass

	    # End while offset<tmpSize
	    try:
	        fh.close()
	    except:
	        # TODO: Do something sensible
	        pass

	    # TODO: Should we check size/md5 here?
	    finished = True
	# End while

    def downloadLayout(self):
	# Actually download the Layout file
	finished = False
	tries = 0

	if os.path.isfile(self.tmpPath):
	    try:
	        os.remove(self.tmpPath)
	    except:
		log.log(0,"error",_("Unable to delete file: ") + self.tmpPath)
		return

	fh = None
	try:
	    fh = open(self.tmpPath, 'wb')
	except:
	    log.log(0,"error",_("Unable to write file: ") + self.tmpPath)
	    return

        while tries < 5 and not finished:
	    tries = tries + 1

	    try:
	        # Fix path attribute so it's just the filename (minus the client path) and trailing .xlf
	        shortPath = self.tmpPath.replace(config.get('Main','libraryDir') + os.sep,'',1)
	        shortPath = self.tmpPath.replace('.xlf','',1)

	        response = self.parent.xmds.GetFile(shortPath,self.tmpType,0,0)
	        fh.write(response + '\n')
	        fh.flush()
	    except RuntimeError:
	        # TODO: Do something sensible
	        pass

	    try:
	        fh.close()
	    except:
	        # TODO: Do something sensible
	        pass

	    # TODO: Should we check size/md5 here?
	    finished = True
	# End while

#### Finish Download Manager

#### Layout/Region Management
class XiboLayoutManager(Thread):
    def __init__(self,parent,player,layout,zindex=0,opacity=1.0,hold=False):
        log.log(3,"info",_("New XiboLayoutManager instance created."))
        self.p = player
        self.l = layout
	self.zindex = zindex
        self.parent = parent
	self.opacity = opacity
	self.regions = []
	self.layoutNodeName = None
	self.layoutNodeNameExt = "-" + str(self.p.nextUniqueId())
	self.layoutExpired = False
	self.isPlaying = False
	self.hold = hold
        Thread.__init__(self)
    
    def run(self):
	self.isPlaying = True
        log.log(2,"info",_("XiboLayoutManager instance running."))
	
	# Add a DIV to contain the whole layout (for transitioning whole layouts in to one another)
	# TODO: Take account of the zindex parameter for transitions. Should this layout sit on top or underneath?
	# Ensure that the layoutNodeName is unique on the player (incase we have to transition to ourself)
	self.layoutNodeName = 'L' + str(self.l.layoutID) + self.layoutNodeNameExt

	# Create the XML that will render the layoutNode.
	tmpXML = '<div id="' + self.layoutNodeName + '" width="' + str(self.l.sWidth) + '" height="' + str(self.l.sHeight) + '" x="' + str(self.l.offsetX) + '" y="' + str(self.l.offsetY) + '" opacity="' + str(self.opacity) + '" />'
	self.p.enqueue('add',(tmpXML,'screen'))

	# TODO: Fix background colour
	# Add a ColorNode and maybe ImageNode to the layout div to draw the background

	# This code will work with libavg > 0.8.x
	# tmpXML = '<colornode fillcolor="' + self.l.backgroundColour + '" id="bgColor' + self.layoutNodeNameExt + '" />'
	# self.p.enqueue('add',(tmpXML,self.layoutNodeName))

	if self.l.backgroundImage != None:
		tmpXML = '<image href="' + config.get('Main','libraryDir') + os.sep + str(self.l.backgroundImage) + '" width="' + str(self.l.sWidth) + '" height="' + str(self.l.sHeight) + '" id="bg' + self.layoutNodeNameExt + '" />'
		self.p.enqueue('add',(tmpXML,self.layoutNodeName))

	# Break layout in to regions
	# Spawn a region manager for each region and then start them all running
	# Log each region in an array for checking later.
	for cn in self.l.children():
		if cn.nodeType == cn.ELEMENT_NODE and cn.localName == "region":
			log.log(1,"info","Encountered region")
			# Create a new Region Manager Thread and kick it running.
			# Pass in cn since it contains the XML for the whole region
		        tmpRegion = XiboRegionManager(self, self.p, self.layoutNodeName, self.layoutNodeNameExt, cn)
		        log.log(2,"info",_("XiboLayoutManager: run() -> Starting new XiboRegionManager."))
			# TODO: Instead of starting here, we need to sort the regions array by zindex attribute
			# then start in ascending order to ensure rendering happens in layers correctly.
		        tmpRegion.start()
			# Store a reference to the region so we can talk to it later
			self.regions.append(tmpRegion)
			
    
    def regionElapsed(self):
	log.log(2,"info",_("Region elapsed. Checking if layout has elapsed"))

	allExpired = True
	for i in self.regions:
		if i.regionExpired == False:
			log.log(3,"info",_("Region " + i.regionNodeName + " has not expired. Waiting"))
			allExpired = False

	if allExpired:
		log.log(2,"info",_("All regions have expired. Marking layout as expired"))
		self.layoutExpired = True

		# TODO: Check that there is something else to show before killing
		#       the layout off completely.


		# Enqueue region exit transitions by calling the dispose method on each regionManager
		for i in self.regions:
			i.dispose()

		return True
	else:
		return False

    def regionDisposed(self):
	log.log(2,"info",_("Region disposed. Checking if all regions have disposed"))

	allExpired = True
	for i in self.regions:
		if i.disposed == False:
			log.log(3,"info",_("Region " + i.regionNodeName + " has not disposed. Waiting"))
			allExpired = False

	if allExpired == True:
		log.log(2,"info",_("All regions have disposed. Marking layout as disposed"))
		self.layoutDisposed = True

		if self.hold:
		    log.log(2,"info",_("Holding the splash screen until we're told otherwise"))
		else:
		    log.log(2,"info",_("LayoutManager->parent->nextLayout()"))
		    self.parent.nextLayout()
	
    def dispose(self):
	# Enqueue region exit transitions by calling the dispose method on each regionManager
	for i in self.regions:
		i.dispose()

	# TODO: Remove this? The exiting layout should be left for a transition object to transition with.
	#       Leaving in place for testing though.
        # self.p.enqueue("reset","")

class XiboRegionManager(Thread):
    def __init__(self,parent,player,layoutNodeName,layoutNodeNameExt,cn):
        log.log(3,"info",_("New XiboRegionManager instance created."))
        Thread.__init__(self)
	# Semaphore used to block this thread's execution once it has passed control off to the Media thread.
	# Lock is released by a callback from the libavg player (which returns control to this thread such that the
	# player thread never blocks.
	self.lock = Semaphore()
	self.tLock = Semaphore()

	# Variables
	self.p = player
	self.parent = parent
	self.regionNode = cn
	self.layoutNodeName = layoutNodeName
	self.layoutNodeNameExt = layoutNodeNameExt
	self.regionExpired = False
	self.regionNodeNameExt = "-" + str(self.p.nextUniqueId())
	self.regionNodeName = None
	self.width = None
	self.height = None
	self.top = None
	self.left = None
	self.zindex = None
	self.disposed = False
	self.oneItemOnly = False
	self.previousMedia = None
	self.currentMedia = None

	# Calculate the region ID name
	try:
		self.regionNodeName = "R" + str(self.regionNode.attributes['id'].value) + self.regionNodeNameExt
	except KeyError:
		log.log(1,"error",_("Region XLF is invalid. Missing required id attribute"))
		self.regionExpired = True
		self.parent.regionElapsed()
		return


	# Calculate the region width
	try:
		self.width = int(self.regionNode.attributes['width'].value) * parent.l.scaleFactor
	except KeyError:
		log.log(1,"error",_("Region XLF is invalid. Missing required width attribute"))
		self.regionExpired = True
		self.parent.regionElapsed()
		return

	# Calculate the region height
	try:
		self.height =  int(self.regionNode.attributes['height'].value) * parent.l.scaleFactor
	except KeyError:
		log.log(1,"error",_("Region XLF is invalid. Missing required height attribute"))
		self.regionExpired = True
		self.parent.regionElapsed()
		return

	# Calculate the region top
	try:
		self.top = int(self.regionNode.attributes['top'].value) * parent.l.scaleFactor
	except KeyError:
		log.log(1,"error",_("Region XLF is invalid. Missing required top attribute"))
		self.regionExpired = True
		self.parent.regionElapsed()
		return

	# Calculate the region left
	try:
		self.left = int(self.regionNode.attributes['left'].value) * parent.l.scaleFactor
	except KeyError:
		log.log(1,"error",_("Region XLF is invalid. Missing required left attribute"))
		self.regionExpired = True
		self.parent.regionElapsed()
		return

	# Get region zindex
	try:
		self.zindex = int(self.regionNode.attributes['zindex'].value)
	except KeyError:
		self.zindex = 1

    def run(self):
	self.lock.acquire()
	self.tLock.acquire()
        log.log(3,"info",_("New XiboRegionManager instance running for region:") + self.regionNodeName)
	# Create a div for the region and add it
	tmpXML = '<div id="' + self.regionNodeName + '" width="' + str(self.width) + '" height="' + str(self.height) + '" x="' + str(self.left) + '" y="' + str(self.top) + '" opacity="1.0" />'
	self.p.enqueue('add',(tmpXML,self.layoutNodeName))

	#  * Iterate through the media items
	#  -> For each media, display on screen and set a timer to cause the next item to be shown
	#  -> attempt to acquire self.lock - which will block this thread. We will be woken by the callback
	#     to next() by the libavg player.
	#  * When all items complete, mark region complete by setting regionExpired = True and calling parent.regionElapsed()
	mediaCount = 0

	while self.disposed == False and self.oneItemOnly == False:
		for cn in self.regionNode.childNodes:
			if cn.nodeType == cn.ELEMENT_NODE and cn.localName == "media":
				log.log(3,"info","Encountered media")
				mediaCount = mediaCount + 1
				if self.disposed == False:
					type = str(cn.attributes['type'].value)
					type = type[0:1].upper() + type[1:]
					log.log(4,"info","Media is of type: " + type)
					try:
						import plugins.media
						__import__("plugins.media." + type + "Media",None,None,[''])
						self.currentMedia = eval("plugins.media." + type + "Media." + type + "Media")(log,self,self.p,cn)

						# Transition between media here...
						import plugins.transitions
						try:
							tmp1 = str(self.previousMedia.options['transOut'])
							tmp1 = tmp1[0:1].upper() + tmp1[1:]
						except:
							tmp1 = ""
						
						try:
							tmp2 = str(self.currentMedia.options['transIn'])
							tmp2 = tmp2[0:1].upper() + tmp2[1:]
						except:
							tmp2 = ""

						trans = (tmp1,tmp2)
						
						log.log(3,"info",_("Beginning transitions: " + str(trans)))
						# The two transitions match. Let one plugin handle both.
						if (trans[0] == trans[1]) and trans[0] != "":
							self.currentMedia.start()
							try:
								__import__("plugins.transitions." + trans[0] + "Transition",None,None,[''])
								tmpTransition = eval("plugins.transitions." + trans[0] + "Transition." + trans[0] + "Transition")(log,self.p,self.previousMedia,self.currentMedia,self.tNext)
								tmpTransition.start()
							except ImportError:
								__import__("plugins.transitions.DefaultTransition",None,None,[''])
								tmpTransition = plugins.transitions.DefaultTransition.DefaultTransition(log,self.p,self.previousMedia,self.currentMedia,self.tNext)
								tmpTransition.start()
							self.tLock.acquire()
						else:							
					
						# The two transitions don't match.
						# Create two transition plugins and run them sequentially.
							if (trans[0] != ""):
								try:
									__import__("plugins.transitions." + trans[0] + "Transition",None,None,[''])
									tmpTransition = eval("plugins.transitions." + trans[0] + "Transition." + trans[0] + "Transition")(log,self.p,self.previousMedia,None,self.tNext)
									tmpTransition.start()
								except ImportError:
									__import__("plugins.transitions.DefaultTransition",None,None,[''])
									tmpTransition = plugins.transitions.DefaultTransition.DefaultTransition(log,self.p,self.previousMedia,None,self.tNext)
									tmpTransition.start()
								self.tLock.acquire()

							if (trans[1] != ""):
								self.currentMedia.start()
								try:
									__import__("plugins.transitions." + trans[1] + "Transition",None,None,[''])
									tmpTransition = eval("plugins.transitions." + trans[1] + "Transition." + trans[1] + "Transition")(log,self.p,None,self.currentMedia,self.tNext)
									tmpTransition.start()
								except ImportError:
									__import__("plugins.transitions.DefaultTransition",None,None,[''])
									tmpTransition = plugins.transitions.DefaultTransition.DefaultTransition(log,self.p,None,self.currentMedia,self.tNext)
									tmpTransition.start()
								self.tLock.acquire()
							else:
								self.currentMedia.start()
						# Cleanup
						try:						
							self.p.enqueue('del',self.previousMedia.mediaNodeName)								
						except AttributeError:
							pass

						# Wait for the new media to finish
						self.lock.acquire()
						self.previousMedia = self.currentMedia
						self.currentMedia = None
					except ImportError as detail:
						log.log(0,"error","Missing media plugin for media type " + type + ": " + str(detail))
						# TODO: Do something with this layout? Blacklist?
						self.lock.release()				
	
		self.regionExpired = True
		if self.parent.regionElapsed():
			# If regionElapsed returns True, then the layout is on its way out so stop looping
			# Acheived by pretending to be a single item region
			self.oneItemOnly = True

		# If there's only one item, render it and leave it alone!
		if mediaCount == 1:
			self.oneItemOnly = True
		        log.log(3,"info",_("Region has only one media: ") + self.regionNodeName)
	# End while loop

    def next(self):
	# Release the lock semaphore so that the run() method of the thread can continue.
	# Called by a callback from libavg
        # log.log(3,"info",_("XiboRegionManager") + " " + self.regionNodeName + ": " + _("Next Media Item"))

	# Do nothing if the layout has already been removed from the screen
	if self.disposed == True:
		return

	self.lock.release()

    def tNext(self):
	if self.disposed == True:
		return

	self.tLock.release()

    def dispose(self):
	log.log(5,"info",self.regionNodeName + " is disposing.")
	rOptions = {}
	oNode = None

	# Perform any region exit transitions
	for cn in self.regionNode.childNodes:
		if cn.nodeType == cn.ELEMENT_NODE and cn.localName == "options":
			oNode = cn

	try:	
		for cn in oNode.childNodes:
			if cn.localName != None:
				rOptions[str(cn.localName)] = cn.childNodes[0].nodeValue
				log.log(5,"info","Region Options: " + str(cn.localName) + " -> " + str(cn.childNodes[0].nodeValue))
	except AttributeError:
		rOptions["transOut"] = ""

	# Make the transition objects and pass in options
	# Once animation complete, they should call back to self.disposeTransitionComplete()
	transOut = str(rOptions["transOut"])
	if (transOut != ""):
		import plugins.transitions
		transOut = transOut[0:1].upper() + transOut[1:]
		log.log(5,"info",self.regionNodeName + " starting exit transition")
		try:
			__import__("plugins.transitions." + transOut + "Transition",None,None,[''])
			tmpTransition = eval("plugins.transitions." + transOut + "Transition." + transOut + "Transition")(log,self.p,self.previousMedia,None,self.disposeTransitionComplete,rOptions,None)
			tmpTransition.start()
			log.log(5,"info",self.regionNodeName + " control passed to Transition object.")
		except ImportError as detail:
			log.log(3,"error",self.regionNodeName + ": Unable to import requested Transition plugin. " + str(detail))
			self.disposeTransitionComplete()
	else:
		self.disposeTransitionComplete()

    def disposeTransitionComplete(self):
	# Notify the LayoutManager when these are complete.
	log.log(5,"info",self.regionNodeName + " is disposed.")
	self.disposed = True
	self.parent.regionDisposed()
	
#### Finish Layout/Region Managment

#### Scheduler Classes
class XiboLayout:
    def __init__(self,layoutID):
        self.layoutID = layoutID
	self.builtWithNoXLF = False
	self.schedule = ""
	self.layoutNode = None
	self.iter = None

	self.playerWidth = int(config.get('Main','width'))
	self.playerHeight = int(config.get('Main','height'))
	
	# Attributes
	self.width = None
	self.height = None
	self.sWidth = None
	self.sHeight = None
	self.offsetX = 0
	self.offsetY = 0
	self.scaleFactor = 1
	self.backgroundImage = None
	self.backgroundColour = None

	# Checks
	# TODO: Check these are appropriate defaults.
	self.schemaCheck = True
	self.mediaCheck = True
	self.scheduleCheck = True

	# Read XLF from file (if it exists)
	# Set builtWithNoXLF = True if it doesn't
	try:
		log.log(3,"info",_("Loading layout ID") + " " + self.layoutID + " " + _("from file") + " " + config.get('Main','libraryDir') + os.sep + self.layoutID + '.xlf')
		self.doc = minidom.parse(config.get('Main','libraryDir') + os.sep + self.layoutID + '.xlf')

		# Find the layout node and store it
		for e in self.doc.childNodes:
			if e.nodeType == e.ELEMENT_NODE and e.localName == "layout":
				self.layoutNode = e

		# Check the layout's schemaVersion matches the version this client understands
		try:
			xlfSchemaVersion = int(self.layoutNode.attributes['schemaVersion'].value)
		except KeyError:
			log.log(1,"error",_("Layout has no schemaVersion attribute and cannot be shown by this client"))
			self.schemaCheck = False
			return			

		if xlfSchemaVersion != schemaVersion:
			# Layout has incorrect schemaVersion.
			# Set the flag so the scheduler doesn't present this to the display
			log.log(1,"error",_("Layout has incorrect schemaVersion attribute and cannot be shown by this client.") + " " + str(xlfSchemaVersion) + " != " + str(schemaVersion))
			self.schemaCheck = False
			return
		else:
			self.schemaCheck = True

		# Setup variables from the layout node
		try:
			self.width = int(self.layoutNode.attributes['width'].value)
			self.height = int(self.layoutNode.attributes['height'].value)
			self.backgroundColour = str(self.layoutNode.attributes['bgcolor'].value)[1:]
		except KeyError:
			# Layout invalid as a required key was not present
			log.log(1,"error",_("Layout XLF is invalid. Missing required attributes"))

		try:
			self.backgroundImage = self.layoutNode.attributes['background'].value
		except KeyError:
			# Optional attributes, so pass on error.
			pass

		# Work out layout scaling and offset and set appropriate variables
		self.scaleFactor = min((self.playerWidth / float(self.width)),(self.playerHeight / float(self.height)))
		self.sWidth = int(self.width * self.scaleFactor)
		self.sHeight = int(self.height * self.scaleFactor)
		self.offsetX = abs(self.playerWidth - self.sWidth) / 2
		self.offsetY = abs(self.playerHeight - self.sHeight) / 2

		log.log(5,"debug",_("Screen Dimensions:") + " " + str(self.playerWidth) + "x" + str(self.playerHeight))
		log.log(5,"debug",_("Layout Dimensions:") + " " + str(self.width) + "x" + str(self.height))
		log.log(5,"debug",_("Scaled Dimensions:") + " " + str(self.sWidth) + "x" + str(self.sHeight))
		log.log(5,"debug",_("Offset Dimensions:") + " " + str(self.offsetX) + "x" + str(self.offsetY))
		log.log(5,"debug",_("Scale Ratio:") + " " + str(self.scaleFactor))

		# Present the children of the layout node for further parsing
		self.iter = self.layoutNode.childNodes

	except IOError:
		# File doesn't exist. Keep the layout object for the
		# schedule information it may contain later.
		log.log(3,"info",_("File does not exist. Marking layout built without XLF file"))
		self.builtWithNoXLF = True
	
    def canRun(self):
		return self.schemaCheck and self.mediaCheck and self.scheduleCheck

    def resetSchedule(self):
	pass

    def addSchedule(self,fromDt,toDt):
	pass

    def children(self):
	return self.iter
        
class DummyScheduler(XiboScheduler):
    "Dummy scheduler - returns a list of layouts in rotation forever"
#    layoutList = ['1', '2', '3']
    layoutList = ['5']
    layoutIndex = 0
    
    def __init__(self,xmds):
        Thread.__init__(self)
    
    def run(self):
        pass
    
    def nextLayout(self):
        "Return the next valid layout"
        
        layout = XiboLayout(self.layoutList[self.layoutIndex])
        self.layoutIndex = self.layoutIndex + 1

        if self.layoutIndex == len(self.layoutList):
            self.layoutIndex = 0
        
	if layout.canRun() == False:
	        log.log(3,"info",_("DummyScheduler: nextLayout() -> ") + str(layout.layoutID) + _(" is not ready to run."))
		return self.nextLayout()
	else:
	        log.log(3,"info",_("DummyScheduler: nextLayout() -> ") + str(layout.layoutID))
	        return layout
    
    def hasNext(self):
        "Return true if there are more layouts, otherwise false"
        log.log(3,"info",_("DummyScheduler: hasNext() -> true"))
        return True
#### Finish Scheduler Classes

#### Webservice
class XMDSException(Exception):
    def __init__(self, value):
	self.value = value
    def __str__(self):
	return repr(self.value)

class XMDS:
    def __init__(self):
	self.hasInitialised = False
	
	salt = None
	try:
	    salt = config.get('Main','xmdsClientID')
	except:
 	    log.log(0,"error",_("No XMDS Client ID specified in your configuration"))
	    log.log(0,"error",_("Please check your xmdsClientID configuration option"))
	    exit(1)

	self.uuid = uuid.uuid5(uuid.NAMESPACE_DNS, salt)
	# Convert the UUID in to a SHA1 hash
	self.uuid = hashlib.sha1(str(self.uuid)).hexdigest()

	self.name = None
	try:
	    self.name = config.get('Main','xmdsClientName')
	except:
	    pass

	if self.name == None or self.name == "":
	    import platform
	    self.name = platform.node()
	    
	self.key = None
	try:
	    self.key = config.get('Main','xmdsKey')
	except:
	    log.log(0,"error",_("No XMDS server key specified in your configuration"))
	    log.log(0,"error",_("Please check your xmdsKey configuration option"))
	    exit(1)

	# Setup a Proxy for XMDS
	self.xmdsUrl = None
	try:
	    self.xmdsUrl = config.get('Main','xmdsUrl')
	    if self.xmdsUrl[-1] != "/":
		self.xmdsUrl = self.xmdsUrl + "/"
	    self.xmdsUrl = self.xmdsUrl + "xmds.php"
	except ConfigParser.NoOptionError:
	    log.log(0,"error",_("No XMDS URL specified in your configuration"))
	    log.log(0,"error",_("Please check your xmdsUrl configuration option"))
	    exit(1)

	self.wsdlFile = self.xmdsUrl + '?wsdl'

    def getUUID(self):
	return str(self.uuid)

    def getName(self):
	return str(self.name)

    def getKey(self):
	return str(self.key)

    def check(self):
	if self.hasInitialised:
	    return True
	else:
	    self.server = None
	    tries = 0
	    while self.server == None and tries < 3:
		tries = tries + 1
		log.log(2,"info",_("Connecting to XMDS at ") + self.xmdsUrl + " " + _("Attempt") + " " + str(tries))
	        try:
		    self.server = WSDL.Proxy(self.wsdlFile)
		    self.hasInitialised = True
	        except xml.parsers.expat.ExpatError:
		    log.log(0,"error",_("Could not connect to XMDS."))
	    # End While
	    if self.server == None:
		return False
	
	return True

    def RequiredFiles(self):
	"""Connect to XMDS and get a list of required files"""
	req = None
	if self.check():
	    try:
		# TODO: Change the final arguement to use the globally defined schema version once
		# there is a server that supports the schema to test against.
		req = self.server.RequiredFiles(self.getKey(),self.getUUID(),"1")
	    except SOAPpy.Types.faultType, err:
		log.log(0,"error",str(err))
		raise XMDSException("RequiredFiles: Incorrect arguments passed to XMDS.")
	    except SOAPpy.Errors.HTTPError, err:
		log.log(0,"error",str(err))
		raise XMDSException("RequiredFiles: HTTP error connecting to XMDS.")
	    except socket.error, err:
		log.log(0,"error",str(err))
		raise XMDSException("RequiredFiles: socket error connecting to XMDS.")
	else:
	    log.log(0,"error","XMDS could not be initialised")
	    raise XMDSException("XMDS could not be initialised")

	return req

    def GetFile(self,tmpPath,tmpType,tmpOffset,tmpChunk):
	"""Connect to XMDS and download a file"""
	response = None
	if self.check():
	    try:
		# TODO: Change the final arguement to use the globally defined schema version once
		# there is a server that supports the schema to test against.
		response = self.server.GetFile(self.getKey(),self.getUUID(),tmpPath,tmpType,tmpOffset,tmpChunk,"1")
	    except SOAPpy.Types.faultType, err:
		log.log(0,"error",str(err))
		raise XMDSException("GetFile: Incorrect arguments passed to XMDS.")
	    except SOAPpy.Errors.HTTPError, err:
		log.log(0,"error",str(err))
		raise XMDSException("GetFile: HTTP error connecting to XMDS.")
	    except socket.error, err:
		log.log(0,"error",str(err))
		raise XMDSException("GetFile: socket error connecting to XMDS.")
	else:
	    log.log(0,"error","XMDS could not be initialised")
	    raise XMDSException("XMDS could not be initialised")

	return response

    def RegisterDisplay(self):
	"""Connect to XMDS and attempt to register the client"""
	requireXMDS = False
	try:
	    if config.get('Main','requireXMDS') == "true":
		requireXMDS = True
	except:
	    pass

	if requireXMDS:
	    regReturn = ""
	    regOK = "Display is active and ready to start."
	    regInterval = 20
	    tries = 0
	    while regReturn != regOK:
		tries = tries + 1
		if self.check():
		    #TODO: Change the final arguement to use the globally defined schema version once
		    # there is a server that supports the schema to test against.
		    try:
		        regReturn = self.server.RegisterDisplay(self.getKey(),self.getUUID(),self.getName(),"1")
		        log.log(0,"info",regReturn)
		    except SOAPpy.Types.faultType, err:
			log.log(0,"error",str(err))
		    except SOAPpy.Errors.HTTPError, err:
			log.log(0,"error",str(err))
		    except socket.error, err:
			log.log(0,"error",str(err))

		if regReturn != regOK:
		    # We're not licensed. Sleep 20 * tries seconds and try again.
		    log.log(0,"info",_("Waiting for license to be issued, or connection restored to the webservice. Set requireXMDS=false to skip this check"))
		    time.sleep(regInterval * tries)
	    # End While
	else:
	    if self.check():
		#TODO: Change the final arguement to use the globally defined schema version once
		# there  is a server that supports the schema to test against.
		try:
	            log.log(0,"info",self.server.RegisterDisplay(self.getKey(),self.getUUID(),self.getName(),"1"))
		except SOAPpy.Types.faultType, err:
		    log.log(0,"error",str(err))
		except SOAPpy.Errors.HTTPError, err:
		    log.log(0,"error",str(err))
		except socket.error, err:
		    log.log(0,"error",str(err))
	    
#### Finish Webservice	

class XiboDisplayManager:
    def __init__(self):
        pass
    
    def run(self):
        log.log(2,"info",_("New DisplayManager started"))

        # Create a XiboPlayer and start it running.
        self.Player = XiboPlayer()
	self.Player.start()

	# TODO: Display the splash screen
	self.currentLM = XiboLayoutManager(self, self.Player, XiboLayout('0'), 0, 1.0, True)
        self.currentLM.start()
		
	self.xmds = XMDS()
        
        # Load a DownloadManager and start it running in its own thread
        try:
            downloaderName = config.get('Main','downloader')
            self.downloader = eval(downloaderName)(self.xmds)
            self.downloader.start()
            log.log(2,"info",_("Loaded Download Manager ") + downloaderName)
        except ConfigParser.NoOptionError:
            log.log(0,"error",_("No DownloadManager specified in your configuration."))
            log.log(0,"error",_("Please check your Download Manager configuration."))
            exit(1)
        except:
            log.log(0,"error",downloaderName + _(" does not implement the methods required to be a Xibo DownloadManager or does not exist."))
            log.log(0,"error",_("Please check your Download Manager configuration.") + str(e))
            exit(1)
        # End of DownloadManager init
        
        # Load a scheduler and start it running in its own thread
        try:
            schedulerName = config.get('Main','scheduler')
            self.scheduler = eval(schedulerName)(self.xmds)
            self.scheduler.start()
            log.log(2,"info",_("Loaded Scheduler ") + schedulerName)
        except ConfigParser.NoOptionError:
            log.log(0,"error",_("No Scheduler specified in your configuration"))
            log.log(0,"error",_("Please check your scheduler configuration."))
            exit(1)
        except:
            log.log(0,"error",schedulerName + _(" does not implement the methods required to be a Xibo Scheduler or does not exist."))
            log.log(0,"error",_("Please check your scheduler configuration."))
            exit(1)
        # End of scheduler init

	# Attempt to register with the webservice.
	# The RegisterDisplay code will block here if
	# we're configured not to play cached content on startup.
	self.xmds.RegisterDisplay()
	
        # Done with the splash screen. Let it advance...
	self.currentLM.hold = False
	self.currentLM.regionDisposed()
            
    def nextLayout(self):
	# TODO: Whole function is wrong. This is where layout transitions should be supported.
	# Needs careful consideration.

        # Deal with any existing LayoutManagers that might still be running
	try:        
		if self.currentLM.isRunning == True:
        	    self.currentLM.dispose()
	except:
		pass
	self.Player.enqueue("reset","")        

        # New LayoutManager
        self.currentLM = XiboLayoutManager(self, self.Player, self.scheduler.nextLayout())
        log.log(2,"info",_("XiboLayoutManager: nextLayout() -> Starting new XiboLayoutManager with layout ") + str(self.currentLM.l.layoutID))
        self.currentLM.start()

class XiboPlayer(Thread):
	"Class to handle libavg interactions"
	def __init__(self):
		Thread.__init__(self)
		self.q = Queue.Queue(0)
		self.uniqueId = 0

	def getDimensions(self):
		return (self.player.width, self.player.height)

	def getElementByID(self,id):
		return self.player.getElementByID(id)

	def nextUniqueId(self):
		# This is just to ensure there are never two identically named nodes on the
		# player at once.
		# When we hit 100 times, reset to 0 as those nodes should be long gone.
		if self.uniqueId > 100:
			self.uniqueId = 0

		self.uniqueId += 1
		return self.uniqueId

	def run(self):
		log.log(1,"info",_("New XiboPlayer running"))
		self.player = avg.Player()
		if config.get('Main','fullscreen') == "true":
			self.player.setResolution(True,int(config.get('Main','width')),int(config.get('Main','height')),int(config.get('Main','bpp')))
		else:
			self.player.setResolution(False,int(config.get('Main','width')),int(config.get('Main','height')),int(config.get('Main','bpp')))
		#self.player.loadPlugin("ColorNode")
		self.player.showCursor(0)
		self.player.loadString('<avg id="main" width="' + config.get('Main','width') + '" height="' + config.get('Main','height') + '"><div id="screen"></div></avg>')
		self.player.setOnFrameHandler(self.frameHandle)
		self.player.play()

	def enqueue(self,command,data):
		log.log(3,"info","Enqueue: " + str(command) + " " + str(data))
		self.q.put((command,data))
		log.log(3,"info",_("Queue length is now") + " " + str(self.q.qsize()))

	def frameHandle(self):
		"Called on each new libavg frame. Takes queued commands and executes them"
		try:
			result = self.q.get(False)
			cmd = result[0]
			data = result[1]
			if cmd == "add":
				newNode = self.player.createNode(data[0])
				parentNode = self.player.getElementByID(data[1])
				parentNode.appendChild(newNode)
				log.log(5,"debug","Added new node to " + str(data[1]))
			elif cmd == "del":
				currentNode = self.player.getElementByID(data)
				parentNode = currentNode.getParent()
				parentNode.removeChild(currentNode)
				log.log(5,"debug","Removed node " + str(data))
			elif cmd == "reset":
				parentNode = self.player.getElementByID("screen")
				numChildren = parentNode.getNumChildren()
				log.log(5,"debug","Reset. Node has " + str(numChildren) + " nodes")
				for i in range(0,numChildren):
					try:
						node = parentNode.getChild(i)
						parentNode.removeChild(node)
						log.log(5,"debug","Removed child node at position " + str(i))
					except:
						pass
			elif cmd == "anim":
				currentNode = self.player.getElementByID(data[1])
				if data[0] == "fadeIn":
					animation = anim.fadeIn(currentNode,data[2])
				if data[0] == "fadeOut":
					animation = anim.fadeOut(currentNode,data[2])
				if data[0] == "linear":
					animation = anim.LinearAnim(currentNode,data[3],data[2],data[4],data[5],False,data[6])
			elif cmd == "play":
				currentNode = self.player.getElementByID(data)
				currentNode.play()
			elif cmd == "pause":
				currentNode = self.player.getElementByID(data)
				currentNode.pause()
			elif cmd == "stop":
				currentNode = self.player.getElementByID(data)
				currentNode.stop()
			elif cmd == "resize":
				currentNode = self.player.getElementByID(data[0])
				dimension = currentNode.getMediaSize()
				# log.log(1,'info',"Media dimensions: " + str(dimension))
				scaleFactor = min((float(data[1]) / dimension[0]),(float(data[2]) / dimension[1]))
				# log.log(1,'info',"Scale Factor: " + str(scaleFactor))
				currentNode.width = dimension[0] * scaleFactor
				currentNode.height = dimension[1] * scaleFactor
			elif cmd == "timer":
				self.player.setTimeout(data[0],data[1])
			elif cmd == "eofCallback":
				currentNode = self.player.getElementByID(data[0])
				currentNode.setEOFCallback(data[1])
			elif cmd == "setOpacity":
				currentNode = self.player.getElementByID(data[0])
				currentNode.opacity = data[1]
			self.q.task_done()
			# Call ourselves again to action any remaining queued items
			# This does not make an infinite loop since when all queued items are processed
			# A Queue.Empty exception is thrown and this whole block is skipped.
			self.frameHandle()
		except Queue.Empty:
			pass
		except RuntimeError as detail:
			log.log(1,"error",_("A runtime error occured: ") + detail)
		except:
			log.log(1,"error",_("An unspecified error occured: ") + str(sys.exc_info()[0]))

class XiboClient:
    "Main Xibo DisplayClient Class. May (in time!) host many DisplayManager classes"

    def __init__(self):
        pass
        
    def play(self):
        global version
        print _("Xibo Client v") + version

	global schemaVersion
        
        print _("Reading default configuration")
        global config
        config = ConfigParser.ConfigParser()
        config.readfp(open('defaults.cfg'))
        
        print _("Reading user configuration")
        config.read(['site.cfg', os.path.expanduser('~/.xibo')])
        
        logLevel = config.get('Logging','logLevel');
        print _("Log Level is: ") + logLevel;
        print _("Logging will be handled by: ") + config.get('Logging','logWriter')
        print _("Switching to new logger")
        
        global log
        logWriter = config.get('Logging','logWriter')
        log = eval(logWriter)(logLevel)
        try:

            log.log(2,"info",_("Switched to new logger"))
        except:
            print logWriter + _(" does not implement the methods required to be a Xibo logWriter or does not exist.")
            print _("Please check your logWriter configuration.")
            exit(1)
        
        self.dm = XiboDisplayManager()
        
        self.dm.run()

# Main - create a XiboClient and run
gettext.install("messages", "locale")

xc = XiboClient()
xc.play()
