# SyncSend
# (c) 2011 A. Jesse Jiryu Davis <ajdavis@cs.oberlin.edu>
# MIT license
# https://github.com/ajdavis/SyncSend

# system imports
import cgi
import urllib

# twisted imports
from twisted.protocols import policies, basic
from twisted.python import log

from twisted.web.http import HTTPChannel, Request, _IdentityTransferDecoder, _ChunkedTransferDecoder, parse_qs

class FileUploadRequest(Request):
    """
    A HTTP request for uploading files. Copied and adapted from twisted.web.http.Request.

    Many simplifications over Twisted's Request: no cookies, no authentication, no SSL
    # TODO: this could inherit from regular requests again
    """
    # OVERRIDABLES
    def fileStarted(self, filename, content_type):
        pass

    def handleFileChunk(self, filename, data):
        pass

    def fileCompleted(self):
        pass

    def __init__(self, channel, path):
        """
        @param channel: the channel we're connected to.
        @param path: URI path
        """
        Request.__init__(self, channel, queued=False)

        # Unlike http.Request, which waits until it's received the whole request to set uri, args,
        # and path, we must do this ASAP
        self.uri = path
        x = self.uri.split('?', 1)

        if len(x) == 1:
            self.path = self.uri
            self.args = {}
        else:
            self.path, argstring = x
            self.args = parse_qs(argstring, 1)

    def handleContentChunk(self, data):
        self.channel.handleContentChunk(data)

class FileUploadChannel(HTTPChannel):
    """
    # TODO: explain
    A receiver for HTTP requests.

    @ivar _transferDecoder: C{None} or an instance of
        L{_ChunkedTransferDecoder} if the request body uses the I{chunked}
        Transfer-Encoding.
    """
    uploadRequestClass = FileUploadRequest
    downloadRequestClass = Request # Standard Twisted HTTP Request

    def __init__(self):
        HTTPChannel.__init__(self)
        self.content_type = None
        self.count_line_data = False
        self.co = self.dataCoroutine()
        self.co.next() # Start up the coroutine

    def dataCoroutine(self):
        line = (yield)

        # IE sends an extraneous empty line (\r\n) after a POST request;
        # eat up such a line, but only ONCE
        if not line.strip(): line = (yield)

        # Get the first line, e.g. "POST /api/foo HTTP/1.1"
        parts = line.split()
        if len(parts) != 3:
            self.transport.write("HTTP/1.1 400 Bad Request\r\n\r\n")
            self.transport.loseConnection()
            return
        command, request, version = parts
        if command not in ('POST', 'GET'):
            self.transport.write("HTTP/1.1 405 Method Not Allowed\r\n\r\n")
            self.transport.loseConnection()
            return

        self.command = command
        self.path = request
        self.version = version
        if self.command == 'POST':
            self.request = self.uploadRequestClass(channel=self, path=self.path)
        else:
            self.request = self.downloadRequestClass(channel=self, queued=False)

        # The base class HTTPChannel keeps a list of enqueued requests; we don't
        # need anything that complex, but we do need to fill out the list so that
        # headerReceived() and other inherited methods still work
        self.requests = [ self.request ]

        line = (yield)

        # Parse header lines
        header = ''
        while line.strip():
            if line[0] in ' \t':
                # Continuation of a header
                # TODO: test multiline headers
                header = header + '\n' + line
            else:
                if header:
                    self.headerReceived(header)
                header = line

            line = (yield)

        # Last line was empty; process final header
        if header:
            self.headerReceived(header)

        # Now we're processing the body
        if not self._transferDecoder:
            # TODO: figure this out -- why doesn't FF send transfer-encoding OR content-length?
            self._transferDecoder = _IdentityTransferDecoder(
                contentLength=None,
                dataCallback=self.handleContentChunk,
                finishCallback=self._finishRequestBody
            )

        self.count_line_data = True # TODO: HACK!!
        print '%s %s' % (self.command, self.path)
        self.request.parseCookies() # TODO: test if we're actually handling cookies well
        print command, 'gotLength()', self.length
        self.request.gotLength(self.length)
        if command == 'GET':
            self.request.requestReceived(self.command, self.path, self.version)

        if command == 'POST':
            ctypes_raw = self.request.requestHeaders.getRawHeaders('content-type')
            self.content_type, type_options = cgi.parse_header(ctypes_raw[0] if ctypes_raw else '')
            if self.content_type.lower() == 'multipart/form-data':
                # Multipart form processing
                boundary = type_options['boundary']
                start_boundary = '--' + boundary
                end_boundary = '--' + boundary + '--'

                # TODO: use coroutine trampolining to let us push this into a subroutine
                # See http://www.vivtek.com/rfc1867.html for a writeup of the format we're parsing here
                line = (yield)
                while line:
                    # TODO: explain
                    extra = ''
                    if line == end_boundary:
                        return # End the coroutine
                    elif line == start_boundary:
                        # We're starting a new value -- either a file or a normal form field
                        line = (yield)
                        assert line.startswith('Content-Disposition:')

                        content_disposition, disp_options = cgi.parse_header(line)
                        if 'filename' in disp_options:
                            filename = disp_options.get('filename', 'file')

                            # This is a header like:
                            # Content-Type: image/jpeg
                            line = (yield)
                            content_type = line.split(':')[1].strip()
                            self.request.fileStarted(filename=filename, content_type=content_type)
                            # Consume a blank line
                            line = (yield)
                            assert not line.strip()

                            self.setRawMode()

                            # TODO: test this for very small chunk sizes and large boundaries
                            # TODO: test for different sequences of form-data and files in the multipart form
                            # TODO: surely there's a more efficient implementation of this?
                            data = (yield)
                            while data:
                                parts = data.split('\r\n' + start_boundary, 1)
                                if len(parts) == 1:
                                    # Data does not contain boundary, we're in the middle of
                                    # a file
                                    head = parts[0]

                                    # If end_boundary is N bytes long, we mustn't send the last
                                    # N bytes we've seen until we know whether they're
                                    # a boundary or not. Save the last N bytes of data.
                                    boundary_len = max(len(start_boundary), len(end_boundary))
                                    self.request.handleFileChunk(filename, head[:-boundary_len])

                                    # Continue reading the file
                                    saved_len = len(head[-boundary_len:])
                                    data = head[-boundary_len:] + (yield)
                                else:
                                    # Data contains boundary, we're at the end of this file,
                                    # and data might contain more form fields, or we might be at
                                    # the end of the request body
                                    # TODO: hack!! can't use setLineMode(tail) because that will
                                    # cause us to re-enter this coroutine
                                    head, extra = parts
                                    if head:
                                        self.request.handleFileChunk(filename, head)
                                    self.request.fileCompleted()

                                    # TODO: cleanup
                                    if extra:
                                        extra = start_boundary + extra

                                    # Continue parsing the body in the outer loop
                                    break

                            self.setLineMode()

                            # TODO: explain
                            line = (yield extra)
                        else:
                            assert content_disposition.split(':')[1].strip() == 'form-data'
                            form_data_name = disp_options['name']

                            # Eat a blank line
                            line = (yield)
                            assert not line.strip()

                            # TODO: multi-line values??
                            form_data_value = (yield)
                            self.request.args[form_data_name] = form_data_value
                            print form_data_name, '=', form_data_value

                            # Continue
                            line = (yield)
                    else:
                        # Line isn't start boundary
                        print 'weird line:', line
                        line = (yield)
            else:
                # We're processing an XMLHTTPRequest file upload -- the body is the file itself
                if self.request.getHeader('X-File-Name'):
                    # filename was quoted with Javascript's encodeURIComponent()
                    filename = urllib.unquote(self.getHeader('X-File-Name'))
                else:
                    filename = 'file'

                self.request.fileStarted(filename, self.content_type)

                self.setRawMode()

                data = (yield)
                while data:
                    self.request.handleFileChunk(filename, data)
                    data = (yield)

                self.request.fileCompleted()

    def lineReceived(self, line):
        self.resetTimeout()
        if (
            self.count_line_data and
            self._transferDecoder and
            getattr(self._transferDecoder, 'contentLength', None) is not None
        ): # TODO: unnecessary?
            self._transferDecoder.contentLength -= len(line) + 2 # Include 2 bytes for the \r\n that's been stripped
        # Feed line to coroutine
        try: self.co.send(line)
        except StopIteration: pass

    def resumeProducing(self):
        """
        Override _PauseableMixin's resumeProducing() to handle a special case:
        0-length files uploaded via AJAX
        """
        # Call super
        basic.LineReceiver.resumeProducing(self)

        if (
            self.content_type.lower() != 'multipart/form-data' and
            self.request.getHeader('content-length') == '0'
        ):
            self._finishRequestBody('')

    def allContentReceived(self):
        # Finish the coroutine
        try: self.co.send(None)
        except StopIteration: pass

        assert self.command == 'POST'

        # Disable the idle timeout, in case this request takes a long
        # time to finish generating output.
        if self.timeOut:
            self._savedTimeOut = self.setTimeout(None)

        self.request.requestReceived(self.command, self.path, self.version)

    def handleContentChunk(self, data):
        # Feed line to coroutine
        extra = ''
        try:
            # TODO: explain
            extra = self.co.send(data)
            if extra:
                self.setLineMode(extra)
        except StopIteration:
            pass
