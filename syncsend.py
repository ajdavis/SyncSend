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
import json
import logging
import os
import urllib
import urlparse

import twisted.web.server
from twisted.web import http
from twisted.internet import reactor

from upload import FileUploadChannel, FileUploadRequest

# Users start sending or receiving files by entering an email address or
# some other unique key. These dicts map from keys to GET requests (the
# receivers) and from keys to PUT or POST requests (the receivers)
post_requests = {}
get_requests = {}

class SyncSendUploadRequest(FileUploadRequest):
    def __init__(self, channel, path):
        FileUploadRequest.__init__(self, channel, path)
        self.file_upload_path = urlparse.urlparse(path).path
        post_requests[self.file_upload_path] = self

    def fileStarted(self, filename, content_type):
        self.filename = filename
        self.content_type = content_type
        self.sent_headers = False
        if self.file_upload_path not in get_requests:
            # Wait for receiver to connect
            self.channel.pauseProducing()

    def _ensure_headers(self, get_request):
        """
        Make sure we write response headers to the download response exactly once
        """
        if not self.sent_headers:
            self.sent_headers = True

            # TODO: unittest weird filenames, determine what the escaping standard is for filenames
            if self.channel.content_type.lower() != 'multipart/form-data':
                # This is an XHR upload, so we know the content-length before the file
                # is starts uploading
                get_request.setHeader(
                    'Content-Length',
                    str(self.channel.length),
                )
            get_request.setHeader(
                'Content-Disposition',
                'attachment; filename="%s"' % self.filename.replace('"', ''),
            )
            get_request.setHeader(
                'Content-Type',
                self.content_type,
            )

    def handleFileChunk(self, filename, data):
        get_request = get_requests[self.file_upload_path]
        self._ensure_headers(get_request)
        get_request.write(data)

    def fileCompleted(self):
        # TODO: multiple files
        get_request = get_requests[self.file_upload_path]
        self._ensure_headers(get_request)

    def process(self):
        if self.channel.content_type.lower() != 'multipart/form-data':
            # For fileuploader.js, which expects a JSON status
            self.write(json.dumps({ 'success': 1 }))
        else:
            # For multipart-form upload, where the user's browser actually
            # navigates to the POST URL when the POST completes; we need
            # to send the user back to the home page
            self.redirect('#?msg=%s' % urllib.quote_plus(
                "Your upload is complete"
            ))
        logging.debug('%s finish()' % self.method)
        self.finish()

        get_requests[self.file_upload_path].finish()
        del post_requests[self.file_upload_path]

class SyncSendDownloadRequest(http.Request):
    def requestReceived(self, command, path, version):
        """
        Receiver has started downloading file
        """
        logging.info('%s %s' % (command, path))
        http.Request.requestReceived(self, command, path, version)
        get_requests[self.path] = self
        if self.path in post_requests:
            post_requests[self.path].channel.resumeProducing()
        return twisted.web.server.NOT_DONE_YET

    def finish(self):
        del get_requests[self.path]
        http.Request.finish(self)

class SyncSendChannel(FileUploadChannel):
    uploadRequestClass = SyncSendUploadRequest
    downloadRequestClass = SyncSendDownloadRequest

class SyncSendHttpFactory(http.HTTPFactory):
    protocol = SyncSendChannel

def parse_args():
    parser = argparse.ArgumentParser(description='SyncSend server')
    parser.add_argument('--pidfile', type=str, help='Where to write the process id')
    parser.add_argument('port', type=int, help='TCP port on which to listen')
    return parser.parse_args()

def main(args):
    if args.pidfile:
        with file(args.pidfile, 'w') as pidfile:
            pidfile.write(str(os.getpid()))
    try:
        reactor.listenTCP(args.port, SyncSendHttpFactory())
        print 'Listening on port', args.port
        reactor.run()
    finally:
        os.unlink(args.pidfile)

if __name__ == "__main__":
    args = parse_args()
    logging.basicConfig(filename='log/syncsend-%s.log' % args.port, level=logging.DEBUG)
    logging.info('Logger up')
    main(args)
