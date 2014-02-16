#!/usr/bin/python
# -*- coding: utf-8 -*-

#
# Xibo - Digitial Signage - http://www.xibo.org.uk
# Copyright (C) 2009-14 Alex Harrington
#
# This file is part of Xibo.
#
# Xibo is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# any later version. 
#
# Xibo is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with Xibo.  If not, see <http://www.gnu.org/licenses/>.
#

from XiboMedia import XiboMedia
from threading import Thread
import shutil
import math
import os
import codecs

class GetResourceBase(XiboMedia):
    def add(self):
        self.tmpPath = os.path.join(self.libraryDir,self.mediaNodeName + "-tmp.html")
        tmpXML = '<browser id="' + self.mediaNodeName + '" opacity="0" width="' + str(self.width) + '" height="' + str(self.height) + \
                '" />'
        self.p.enqueue('add',(tmpXML,self.regionNodeName))

        # Check updateInterval is set.
        # Early releases of the server missed this so catch those.
        try:
            tmpUI = int(self.options['updateInterval'])
        except KeyError:
            self.options['updateInterval'] = 10
        
        # Make sure we have fresh content from the CMS ahead of it needing to run
        # On a layout where the object is actually going to run, this should just return
        # since the pre-run layout check would have cached the content. The only exception
        # being tickers with 0 duration.
        self.download()      

    def run(self):
        # Check if cached content is too old
        # Download new content if needed
        self.download()

        # Copy the cache to temp file
        try:
            shutil.copyfile(os.path.join(self.libraryDir,self.mediaId) + '-cache.xml',
                            self.tmpPath)
        except IOError:
            # Unable to copy file
            # Move on?!
            self.dispose()
            
        try:
            if int(self.options['durationIsPerItem']) == 1:
                # Media item is a ticker with duration per item
                # calculate the duration
                # HTML will contain a comment <!-- NUMITEMS=x -->
                # Find it and get the number or seconds, then
                # update the duration
                
                htmlFile = open(self.tmpPath, "r")

                for line in htmlFile:
                    if "<!-- NUMITEMS=" in line:
                        numItems = line.partition('=')[2]
                        numItems = numItems.partition('-')[0]
                        self.duration = int(numItems) * int(self.duration)
                
        except KeyError:
            pass

        # Display content
        self.p.enqueue('browserNavigate',(self.mediaNodeName,"file://" + os.path.abspath(self.tmpPath),self.finishedRendering))
        self.p.enqueue('timer',(int(self.duration) * 1000,self.parent.next))
        self.startStats()

    def requiredFiles(self):
        return []
	
    def dispose(self):
        self.returnStats()
        self.p.enqueue('del',self.mediaNodeName)
        try:
            os.remove(self.tmpPath)
        except:
            self.log.log(0,"error","Unable to delete file %s" % (self.tmpPath))
        self.parent.tNext()
 
    def finishedRendering(self):
        bo = self.browserOptions()
        optionsTuple = (self.mediaNodeName,bo[0],bo[1])
        self.p.enqueue('browserOptions',optionsTuple)
        self.p.enqueue('executeJavascript', (self.mediaNodeName, "document.body.style.zoom='%s';" % self.parent.parent.l.scaleFactor))
                
        # Make the browser visible
        self.p.enqueue('setOpacity',(self.mediaNodeName,1))
    
    def browserOptions(self):
        scroll = False
        trans = True
              
        return (trans,scroll)

    def download(self):
        # Only process a download if we need it
        if not self.cacheIsExpired():
            return
        
        tries = 3
        i = 0
        flag = False
        
        while i < tries and flag == False:
            try:
                # print "******* Passing in L:%s R:%s M:%s" % (self.parent.parent.l.layoutID,self.parent.regionId,self.mediaId)
                s = self.parent.parent.parent.xmds.GetResource(self.parent.parent.l.layoutID,self.parent.regionId,self.mediaId)
                flag = True
            except:
                self.log.log(1,"error",_("Unable to load Resource from XMDS."))
            i += 1
        
        if flag:
            try:
                try:
                    f = open(os.path.join(self.libraryDir,self.mediaId) + '-cache.xml','w')
                    f.write(s.encode("utf-8"))
                finally:
                    f.close()
            except:
                self.log.log(0,"error",_("Unable to write %s") % os.path.join(self.libraryDir,self.mediaId) + '-cache.xml')

    def cacheIsExpired(self):
        # If libraryDir/self.mediaId-cache.xml exists then check if it's too old to use
        try:
    	    mtime = os.path.getmtime(os.path.join(self.libraryDir,self.mediaId + '-cache.xml'))
            if time.time() < (mtime + (int(self.options['updateInterval']) * 60)):
                return False
        except:
            # File probably doesn't exist. Do nothing.
            pass
        
        return True