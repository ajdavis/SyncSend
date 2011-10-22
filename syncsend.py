# SyncSend
# (c) 2011 A. Jesse Jiryu Davis <ajdavis@cs.oberlin.edu>
# MIT license
# https://github.com/ajdavis/SyncSend
#
# SyncSend server, transfers files from uploading user to downloading user.
# Supports Andrew Valums's fileuploader.js -- all fileuploader-specific
# code should be here, rather than in upload.py
#

import json

import twisted.web.server
from twisted.web import http

from upload import FileUploadChannel, FileUploadRequest, FileDownloadRequest

# Users start sending or receiving files by entering an email address or
# some other unique key. These dicts map from keys to GET requests (the
# receivers) and from keys to PUT or POST requests (the receivers)
post_requests = {}
get_requests = {}

class SyncSendUploadRequest(FileUploadRequest):
    def __init__(self, channel, path, queued):
        FileUploadRequest.__init__(self, channel, path, queued)
        if 'email' in self.args:
            self.file_upload_path = self.path.rstrip('/') + '/' + self.args['email'][0]
        else:
            self.file_upload_path = self.path

        print 'POST', self.file_upload_path
        post_requests[self.file_upload_path] = self

    def fileStarted(self, filename, content_type):
        print 'started', filename
        self.filename = filename
        self.content_type = content_type
        self.sent_headers = False
        if self.file_upload_path not in get_requests:
            # Wait for receiver to connect
            self.channel.pauseProducing()

    def handleFileChunk(self, data):
        get_request = get_requests[self.file_upload_path]
        if not self.sent_headers:
            # TODO: unittest weird filenames, determine what the escaping standard is for filenames
            get_request.setHeader(
                'Content-Disposition',
                'attachment; filename="%s"' % self.filename.replace('"', ''),
            )
            get_request.setHeader(
                'Content-Type',
                self.content_type,
            )
            get_request.setHeader(
                'Content-Length',
                self.content_length,
            )
            self.sent_headers = True

        import time
        time.sleep(.25)
        get_request.write(data)

    def fileCompleted(self):
        # TODO: multiple files
        print 'finished'

    def process(self):
        self.setResponseCode(200)

        # For fileuploader.js, which expects a JSON status
        if not self.is_form:
            self.write(json.dumps({ 'success': 1 }))

        self.finish()

        get_requests[self.file_upload_path].finish()
        del post_requests[self.file_upload_path]

class SyncSendDownloadRequest(FileDownloadRequest):
    def requestReceived(self, command, path, version):
        """
        Receiver has started downloading file
        """
        print 'GET', path
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
