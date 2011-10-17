# SyncSend
# (c) 2011 A. Jesse Jiryu Davis <ajdavis@cs.oberlin.edu>
# MIT license
# https://github.com/ajdavis/SyncSend

import cgi
import twisted.web.server
from twisted.protocols import basic
from twisted.internet import protocol, reactor
from twisted.web import http

from upload import FileUploadChannel, FileUploadRequest, FileDownloadRequest

#
#class FileProxy:
#    def __init__(self, content):
#        """
#        @param content:     A SyncSendContent
#        """
#        self.content = content
#
#    def read(self, length):
#

# Users start sending or receiving files by entering an email address or
# some other unique key. These dicts map from keys to GET requests (the
# receivers) and from keys to PUT or POST requests (the receivers)
post_requests = {}
get_requests = {}

class SyncSendFileReceiver(basic.LineReceiver):
    """
    Receives files encoded as multipart/form-data
    """
    def __init__(self, key, boundary):
        """
        @param key:         The sender's email address or some other unique key
        @param boundary:    The multipart form boundary, like '-----------1234'
        """
        self.key = key
        self.start_boundary = '--' + boundary
        self.end_boundary = '\r\n--' + boundary + '--'

        self.content_type = self.filename = None
        self.file_started = False

        # When we receive the first chunk of an uploaded file, if the receiver hasn't connected
        # yet, we'll need to store that first chunk while we wait for the receiver to connect.
        self.header_buffer = {}
        self.data_buffer = None

    def setReceiverHeader(self, name, value):
        """
        Set a response header for the receiver's HTTP request. If the receiver has connected, set the header,
        otherwise buffer this header and pause sending until the receiver connects.
        """
        if self.key in get_requests:
            get_request = get_requests[self.key]
            print '%s: writing %s = %s' % (
                id(get_request), name, value,
            )

            if len(self.header_buffer):
                # We have just resumed producing
                for buffered_name, buffered_value in self.header_buffer:
                    get_request.setResponseHeader(buffered_name, buffered_value)
                self.header_buffer = {}

            get_request.setHeader(name, value)
        else:
            self.header_buffer[name] = value
            post_requests[self.key].channel.pauseProducing()

    def writeToReceiver(self, data):
        """
        Send data to the file receiver's HTTP request. If the receiver has connected, send the data, otherwise
        buffer this chunk of data and pause sending until the receiver connects.
        """
        if self.key in get_requests:
            get_request = get_requests[self.key]
            print '%s: writing %s of %s' % (
                id(get_request),
                (len(self.data_buffer) if self.data_buffer is not None else 0) + len(data),
                self.filename,
            )

            if self.data_buffer is not None:
                # We have just resumed producing
                get_request.write(self.data_buffer)
                self.data_buffer = None

            get_request.write(data)
        else:
            self.data_buffer = data
            post_requests[self.key].channel.pauseProducing()

    def rawDataReceived(self, data):
        """
        Receive data from the sender. This is called once we have all the headers from the sender, and
        we're now getting the sender's body.
        """
        assert self.file_started
        # TODO: circular buffer!
        if self.end_boundary in data:
            self.writeToReceiver(data.split(self.end_boundary)[0])
        else:
            self.writeToReceiver(data)

    def lineReceived(self, line):
        print line
        if line == self.start_boundary:
            pass
        elif line.startswith('Content-Type:'):
            # This is a header for this part of the multipart form
            self.content_type = line.split(':')[1].strip()
        elif line.startswith('Content-Disposition:'):
            content_disposition, disp_options = cgi.parse_header(line)
            default_filename = 'file'
            self.filename = disp_options.get('filename', default_filename) if disp_options else default_filename
        elif not line:
            # Blank line -- we're going to start receiving raw data after this
            self.file_started = True
            self.setReceiverHeader('Content-Type', self.content_type)
            self.setReceiverHeader('Content-Disposition', 'file; filename=' + self.filename) # TODO
            self.setRawMode()

class SyncSendUploadRequest(FileUploadRequest):
    def gotLength(self, length):
        """
        Called when all headers have been received.
        This request is the sender's POST request.
        """
        FileUploadRequest.gotLength(self, length)
        print 'POST', self.file_upload_path
        post_requests[self.file_upload_path] = self
        if self.file_upload_path not in get_requests:
            # Wait for receiver to connect
            self.channel.pauseProducing()

    def fileStarted(self, filename):
        print 'started', filename

    def handleFileChunk(self, filename, data):
        get_requests[self.file_upload_path].write(data)

    def fileCompleted(self, filename):
        print 'finished', filename
        # TODO: multiple files
        get_requests[self.file_upload_path].finish()

class SyncSendDownloadRequest(FileDownloadRequest):
    def requestReceived(self, command, path, version):
        """
        Receiver has started downloading file
        """
        FileDownloadRequest.requestReceived(self, command, path, version)
        get_requests[self.file_download_path] = self
        if self.file_download_path in post_requests:
            post_requests[self.file_download_path].channel.resumeProducing()
        return twisted.web.server.NOT_DONE_YET

    def finish(self):
        del get_requests[self.file_download_path]
        FileDownloadRequest.finish(self)

class SyncSendChannel(FileUploadChannel):
    uploadRequestClass = SyncSendUploadRequest
    downloadRequestClass = SyncSendDownloadRequest

class SyncSendHttpFactory(http.HTTPFactory):
    protocol = SyncSendChannel

if __name__ == "__main__":
    from twisted.internet import reactor
    reactor.listenTCP(8000, SyncSendHttpFactory())
    reactor.run()
