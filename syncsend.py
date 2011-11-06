# SyncSend
# (c) 2011 A. Jesse Jiryu Davis <ajdavis@cs.oberlin.edu>
# MIT license
# https://github.com/ajdavis/SyncSend
#
# SyncSend server, transfers files from uploading user to downloading user.
# Supports Andrew Valums's fileuploader.js -- all fileuploader-specific
# code should be here, rather than in upload.py
#
import argparse
import cgi

import json

import twisted.web.server
from twisted.web import http
from twisted.internet import reactor

from upload import FileUploadChannel, FileUploadRequest, FileDownloadRequest

# Users start sending or receiving files by entering an email address or
# some other unique key. These dicts map from keys to GET requests (the
# receivers) and from keys to PUT or POST requests (the receivers)
post_requests = {}
get_requests = {}

class SyncSendUploadRequest(FileUploadRequest):
    def __init__(self, channel, path):
        FileUploadRequest.__init__(self, channel, path)
        if 'email' in self.args:
            self.file_upload_path = self.path.rstrip('/') + '/' + self.args['email'][0]
        else:
            self.file_upload_path = self.path

        post_requests[self.file_upload_path] = self

    def gotLength(self, length):
        """
        Set self.is_form to True or False
        """
        # TODO: terser
        ctypes_raw = self.requestHeaders.getRawHeaders('content-type')
        content_type, type_options = cgi.parse_header(ctypes_raw[0] if ctypes_raw else '')
        self.is_form = content_type.lower() == 'multipart/form-data'

    def fileStarted(self, filename, content_type):
        print 'started', filename
        self.filename = filename
        self.content_type = content_type
        self.sent_headers = False
        if self.file_upload_path not in get_requests:
            # Wait for receiver to connect
            print 'pausing upload'
            self.channel.pauseProducing()

    def handleFileChunk(self, filename, data):
        get_request = get_requests[self.file_upload_path]
        if not self.sent_headers:
            # TODO: content-length for XHR uploads
            # TODO: unittest weird filenames, determine what the escaping standard is for filenames
            get_request.setHeader(
                'Content-Disposition',
                'attachment; filename="%s"' % self.filename.replace('"', ''),
            )
            get_request.setHeader(
                'Content-Type',
                self.channel.content_type, # TODO: decouple
            )
            self.sent_headers = True

        get_request.write(data)

    def fileCompleted(self):
        # TODO: multiple files
        print 'finished file upload'

    def process(self):
        print 'POST process()'
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
        print 'GET requestReceived()'
        FileDownloadRequest.requestReceived(self, command, path, version)
        get_requests[self.file_download_path] = self
        if self.file_download_path in post_requests:
            print 'resuming upload'
            post_requests[self.file_download_path].channel.resumeProducing()
        return twisted.web.server.NOT_DONE_YET

    def finish(self):
        print 'GET finish()'
        del get_requests[self.file_download_path]
        FileDownloadRequest.finish(self)

class SyncSendChannel(FileUploadChannel):
    uploadRequestClass = SyncSendUploadRequest
    downloadRequestClass = SyncSendDownloadRequest

class SyncSendHttpFactory(http.HTTPFactory):
    protocol = SyncSendChannel

def parse_args():
    parser = argparse.ArgumentParser(description='SyncSend server')
    parser.add_argument('port', type=int, help='TCP port on which to listen')
    return parser.parse_args()

def main(args):
    reactor.listenTCP(args.port, SyncSendHttpFactory())
    print 'Listening on port', args.port
    reactor.run()

if __name__ == "__main__":
    main(parse_args())
