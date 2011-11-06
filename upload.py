# SyncSend
# (c) 2011 A. Jesse Jiryu Davis <ajdavis@cs.oberlin.edu>
# MIT license
# https://github.com/ajdavis/SyncSend

# system imports
from cStringIO import StringIO
import tempfile
import base64, binascii
import cgi
import socket
import math
import time
import calendar
import urllib
import warnings
import os
from urlparse import urlparse as _urlparse

from zope.interface import implements

# twisted imports
from twisted.internet import interfaces, reactor, protocol, address
from twisted.internet.defer import Deferred
from twisted.protocols import policies, basic
from twisted.python import log
try: # try importing the fast, C version
    from twisted.protocols._c_urlarg import unquote
except ImportError:
    from urllib import unquote

from twisted.web.http_headers import _DictHeaders, Headers
from twisted.web.http import protocol_version, datetimeToString, toChunk, RESPONSES, Request, _IdentityTransferDecoder, StringTransport, _ChunkedTransferDecoder, parse_qs

class FileDownloadRequest(Request):
    def __init__(self, channel, path):
        self.file_download_path = path
        Request.__init__(self, channel=channel, queued=False)

class FileUploadRequest:
    """
    A HTTP request for uploading files. Copied and adapted from twisted.web.http.Request.

    Many simplifications over Twisted's Request: no cookies, no authentication, no SSL
    # TODO: this could inherit from regular requests again
    """
    implements(interfaces.IConsumer)

    producer = None
    finished = 0
    method = "(no method yet)"
    clientproto = "(no clientproto yet)"
    uri = "(no uri yet)"
    startedWriting = 0
    chunked = 0
    sentLength = 0 # content-length of response, or total bytes sent via chunking
    etag = None
    lastModified = None
    path = None
    content = None
    _disconnected = False

    # OVERRIDABLES
    def fileStarted(self, filename, content_type):
        print 'started', filename

    def handleFileChunk(self, filename, data):
        pass

    def fileCompleted(self):
        print 'done'

    # PUBLIC METHODS
    def parseCookies(self):
        pass # TODO

    def __init__(self, channel, path):
        """
        @param channel: the channel we're connected to.
        @param path: URI path
        """
        self.notifications = []
        self.channel = channel
        self.requestHeaders = Headers()
        self.received_cookies = {}
        self.responseHeaders = Headers()
        self.formDataReceiver = None

        # Differs from twisted.http.Request, which starts as None -- we need to store
        # args *as* we stream the request in from the client, not after we've received
        # it all, so we start args as a dict
        self.args = {}

        self.uri = path
        x = self.uri.split('?', 1)

        if len(x) == 1:
            self.path = self.uri
        else:
            self.path, argstring = x
            self.args = parse_qs(argstring, 1)

        self.transport = self.channel.transport


    def __setattr__(self, name, value):
        """
        Support assignment of C{dict} instances to C{received_headers} for
        backwards-compatibility.
        """
        if name == 'received_headers':
            # A property would be nice, but Request is classic.
            self.requestHeaders = headers = Headers()
            for k, v in value.iteritems():
                headers.setRawHeaders(k, [v])
        elif name == 'requestHeaders':
            self.__dict__[name] = value
            self.__dict__['received_headers'] = _DictHeaders(value)
        elif name == 'headers':
            self.responseHeaders = headers = Headers()
            for k, v in value.iteritems():
                headers.setRawHeaders(k, [v])
        elif name == 'responseHeaders':
            self.__dict__[name] = value
            self.__dict__['headers'] = _DictHeaders(value)
        else:
            self.__dict__[name] = value

    def _cleanup(self):
        """
        Called when have finished responding.
        """
        if self.producer:
            log.err(RuntimeError("Producer was not unregistered for %s" % self.uri))
            self.unregisterProducer()
        self.channel.requestDone(self)
        del self.channel
        for d in self.notifications:
            d.callback(None)
        self.notifications = []

    def gotLength(self, length):
        """
        Called when HTTP channel got length of content in this request.

        This method is not intended for users.

        @param length: The length of the request body, as indicated by the
            request headers.  C{None} if the request headers do not indicate a
            length.
        """
        self.content_length = length
        self.received_length = 0

        # TODO: use mimetypes.guess_type if not set here
        ctypes_raw = self.requestHeaders.getRawHeaders('content-type')
        content_type, type_options = cgi.parse_header(ctypes_raw[0] if ctypes_raw else '')
        if content_type.lower() == 'multipart/form-data':
            boundary = type_options['boundary']
            self.formDataReceiver = _FormDataReceiver(boundary=boundary, request=self)
            self.is_form = True
        else:
            # TODO: unittest form and non-form uploads

            # This file is being uploaded with an XMLHTTPRequest
            self.is_form = False
            if self.getHeader('X-File-Name'):
                # filename was quoted with Javascript's encodeURIComponent()
                filename = urllib.unquote(self.getHeader('X-File-Name'))
            else:
                filename = 'file'
            self.fileStarted(
                filename=filename,
                content_type=content_type
            )

            self.channel.setRawMode()

    def handleContentChunk(self, data):
        """
        Write a chunk of data.

        This method is not intended for users.
        """
        self.received_length += len(data)
        if self.is_form:
            self.formDataReceiver.dataReceived(data)
        else:
            self.handleFileChunk(data)
            if self.received_length >= self.content_length:
                self.fileCompleted()

    # consumer interface

    def registerProducer(self, producer, streaming):
        """
        Register a producer.
        """
        if self.producer:
            raise ValueError, "registering producer %s before previous one (%s) was unregistered" % (producer, self.producer)

        self.streamingProducer = streaming
        self.producer = producer

        if streaming:
            producer.pauseProducing()
    def unregisterProducer(self):
        """
        Unregister the producer.
        """
        self.transport.unregisterProducer()
        self.producer = None

    # private http response methods


    # The following is the public interface that people should be
    # writing to.
    def getHeader(self, key):
        """
        Get an HTTP request header.

        @type key: C{str}
        @param key: The name of the header to get the value of.

        @rtype: C{str} or C{NoneType}
        @return: The value of the specified header, or C{None} if that header
            was not present in the request.
        """
        value = self.requestHeaders.getRawHeaders(key)
        if value is not None:
            return value[-1]



    def notifyFinish(self):
        """
        Notify when the response to this request has finished.

        @rtype: L{Deferred}

        @return: A L{Deferred} which will be triggered when the request is
            finished -- with a C{None} value if the request finishes
            successfully or with an error if the request is interrupted by an
            error (for example, the client closing the connection prematurely).
        """
        self.notifications.append(Deferred())
        return self.notifications[-1]


    def finish(self):
        """
        Indicate that all response data has been written to this L{Request}.
        """
        if self._disconnected:
            raise RuntimeError(
                "Request.finish called on a request after its connection was lost; "
                "use Request.notifyFinish to keep track of this.")
        if self.finished:
            warnings.warn("Warning! request.finish called twice.", stacklevel=2)
            return

        if not self.startedWriting:
            # write headers
            self.write('')

        if self.chunked:
            # write last chunk and closing CRLF
            self.transport.write("0\r\n\r\n")

        # log request
        if hasattr(self.channel, "factory"):
            self.channel.factory.log(self)

        self.finished = 1
        self._cleanup()

    def write(self, data):
        """
        Write some data as a result of an HTTP request.  The first
        time this is called, it writes out response data.

        @type data: C{str}
        @param data: Some bytes to be sent as part of the response body.
        """
        if not self.startedWriting:
            self.startedWriting = 1
            version = self.clientproto
            l = []
            l.append('%s %s %s\r\n' % (version, self.code,
                                       self.code_message))
            # if we don't have a content length, we send data in
            # chunked mode, so that we can support pipelining in
            # persistent connections.
            if ((version == "HTTP/1.1") and
                (self.responseHeaders.getRawHeaders('content-length') is None)):
                l.append("%s: %s\r\n" % ('Transfer-Encoding', 'chunked'))
                self.chunked = 1

            if self.lastModified is not None:
                if self.responseHeaders.hasHeader('last-modified'):
                    log.msg("Warning: last-modified specified both in"
                            " header list and lastModified attribute.")
                else:
                    self.responseHeaders.setRawHeaders(
                        'last-modified',
                        [datetimeToString(self.lastModified)])

            for name, values in self.responseHeaders.getAllRawHeaders():
                for value in values:
                    l.append("%s: %s\r\n" % (name, value))

            l.append("\r\n")

            self.transport.writeSequence(l)

            # if this is a "HEAD" request, we shouldn't return any data
            if self.method == "HEAD":
                self.write = lambda data: None
                return

        self.sentLength = self.sentLength + len(data)
        if data:
            if self.chunked:
                self.transport.writeSequence(toChunk(data))
            else:
                self.transport.write(data)

    def setResponseCode(self, code, message=None):
        """
        Set the HTTP response code.
        """
        if not isinstance(code, (int, long)):
            raise TypeError("HTTP response code must be int or long")
        self.code = code
        if message:
            self.code_message = message
        else:
            self.code_message = RESPONSES.get(code, "Unknown Status")


    def setHeader(self, name, value):
        """
        Set an HTTP response header.  Overrides any previously set values for
        this header.

        @type name: C{str}
        @param name: The name of the header for which to set the value.

        @type value: C{str}
        @param value: The value to set for the named header.
        """
        self.responseHeaders.setRawHeaders(name, [value])

    def getAllHeaders(self):
        """
        Return dictionary mapping the names of all received headers to the last
        value received for each.

        Since this method does not return all header information,
        C{self.requestHeaders.getAllRawHeaders()} may be preferred.
        """
        headers = {}
        for k, v in self.requestHeaders.getAllRawHeaders():
            headers[k.lower()] = v[-1]
        return headers


    def getRequestHostname(self):
        """
        Get the hostname that the user passed in to the request.

        This will either use the Host: header (if it is available) or the
        host we are listening on if the header is unavailable.

        @returns: the requested hostname
        @rtype: C{str}
        """
        # XXX This method probably has no unit tests.  I changed it a ton and
        # nothing failed.
        host = self.getHeader('host')
        if host:
            return host.split(':', 1)[0]
        return self.getHost().host


    def getHost(self):
        """
        Get my originally requesting transport's host.

        Don't rely on the 'transport' attribute, since Request objects may be
        copied remotely.  For information on this method's return value, see
        twisted.internet.tcp.Port.
        """
        return self.host

    def getClientIP(self):
        """
        Return the IP address of the client who submitted this request.

        @returns: the client IP address
        @rtype: C{str}
        """
        if isinstance(self.client, address.IPv4Address):
            return self.client.host
        else:
            return None

    def getClient(self):
        if self.client.type != 'TCP':
            return None
        host = self.client.host
        try:
            name, names, addresses = socket.gethostbyaddr(host)
        except socket.error:
            return host
        names.insert(0, name)
        for name in names:
            if '.' in name:
                return name
        return names[0]

    def requestReceived(self, command, path, version):
        """
        By the time this is called, sender has already uploaded the whole file and we've
        sent all the data to receiver; just close out the request
        """
        assert command == 'POST'

        # For Twisted's logging
        self.client = self.channel.transport.getPeer()
        self.host = self.channel.transport.getHost()
        self.clientproto = version
        self.process()

    def process(self):
        """
        Override in subclasses. You should probably call self.finish() here.
        """
        pass

    def connectionLost(self, reason):
        """
        There is no longer a connection for this request to respond over.
        Clean up anything which can't be useful anymore.
        """
        self._disconnected = True
        self.channel = None
        if self.content is not None:
            self.content.close()
        for d in self.notifications:
            d.errback(reason)
        self.notifications = []

class FileUploadChannel(basic.LineReceiver, policies.TimeoutMixin):
    """
    # TODO: explain
    A receiver for HTTP requests.

    @ivar _transferDecoder: C{None} or an instance of
        L{_ChunkedTransferDecoder} if the request body uses the I{chunked}
        Transfer-Encoding.
    """

    maxHeaders = 500 # max number of headers allowed per request

    length = 0

    _savedTimeOut = None
    _receivedHeaderCount = 0

    uploadRequestClass = FileUploadRequest
    downloadRequestClass = FileDownloadRequest

    def __init__(self):
        self.count_line_data = False
        self._transferDecoder = None
        self.co = self.dataCoroutine()
        self.co.next() # Start up the coroutine

    def connectionMade(self):
        self.setTimeout(self.timeOut)

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
        self.request = (
            self.uploadRequestClass if self.command == 'POST' else self.downloadRequestClass
        )(self, self.path)

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

                # TODO: something with these fields?
                fields = {}

                # TODO: use coroutine trampolining to let us push this into a subroutine
                # See http://www.vivtek.com/rfc1867.html for a writeup of the format we're parsing here
                line = (yield)
                while line:
                    print line
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
                            fields[form_data_name] = form_data_value
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

#                if self._transferDecoder.contentLength == 0:
#                    # Empty file; _transferDecoder.dataReceived() won't ever be
#                    # called, so we need to call our finishCallback ourselves
#                    self.request.fileCompleted()
#                    self._finishRequestBody('')
#                else:
                if True:
                    # Content-Length counts down to 0
                    while self._transferDecoder.contentLength:
                        data = (yield)
                        if data:
                            self.request.handleFileChunk(filename, data)

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

    def _finishRequestBody(self, data):
        self.allContentReceived()
        self.setLineMode(data)

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

    def headerReceived(self, line):
        """
        Do pre-processing (for content-length) and store this header away.
        Enforce the per-request header limit.

        @type line: C{str}
        @param line: A line from the header section of a request, excluding the
            line delimiter.
        """
        header, data = line.split(':', 1)
        header = header.lower()
        data = data.strip()
        if header == 'content-length':
            self.length = int(data)
            self._transferDecoder = _IdentityTransferDecoder(
                self.length, self.handleContentChunk, self._finishRequestBody)
        elif header == 'transfer-encoding' and data.lower() == 'chunked':
            self.length = None
            self._transferDecoder = _ChunkedTransferDecoder(
                self.handleContentChunk, self._finishRequestBody)

        reqHeaders = self.request.requestHeaders
        values = reqHeaders.getRawHeaders(header)
        if values is not None:
            values.append(data)
        else:
            reqHeaders.setRawHeaders(header, [data])

        self._receivedHeaderCount += 1
        if self._receivedHeaderCount > self.maxHeaders:
            self.transport.write("HTTP/1.1 400 Bad Request\r\n\r\n")
            self.transport.loseConnection()

    def allContentReceived(self):
        # Finish the coroutine
        if self.co.gi_running:
            try: self.co.send(None)
            except StopIteration: pass

        assert self.command == 'POST'
        self.request.requestReceived(self.command, self.path, self.version)

        # Disable the idle timeout, in case this request takes a long
        # time to finish generating output.
        if self.timeOut:
            self._savedTimeOut = self.setTimeout(None)

    def rawDataReceived(self, data):
        self.resetTimeout()
        self._transferDecoder.dataReceived(data)

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

    def requestDone(self, request):
        """
        Called by request it is done.
        """
        print self.command, 'request done'
        self.transport.loseConnection()

    def timeoutConnection(self):
        log.msg("Timing out client: %s" % str(self.transport.getPeer()))
        policies.TimeoutMixin.timeoutConnection(self)

    def connectionLost(self, reason):
        self.setTimeout(None)
        self.request.connectionLost(reason)
