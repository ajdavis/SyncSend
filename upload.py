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
    def __init__(self, channel, path, queued):
        self.file_download_path = path
        Request.__init__(self, channel=channel, queued=queued)

class Context(object):
    def clear(self):
        delkeys = [k for k in self.__dict__ if not k.startswith('__')]
        for k in delkeys:
            delattr(self, k)

class _FakeTransport:
    def __init__(self):
        self.disconnecting = False
    def pauseProducing(self): pass
    def resumeProducing(self): pass
    def stopProducing(self): pass

class _FormDataReceiver(basic.LineReceiver):
    def __init__(self, boundary, request):
        """
        @param boundary:    The multipart form boundary, like '-----------1234'
        @param request:     A FileUploadRequest
        """
        self.start_boundary = '--' + boundary
        self.end_boundary = '--' + boundary + '--\r\n'
        self.request = request
        self.previous_chunk = ''
        self.transport = _FakeTransport()

    def lineReceived(self, line, context=Context()):
        """
        Process multi-part forms.
        """
        # TODO: if there were some way to turn this into a coroutine with "yield" it'd be far clearer
        # TODO: use the multipart form's content-length
        # See http://www.vivtek.com/rfc1867.html for a writeup of the format we're parsing here
        print line
        if line == self.start_boundary:
            context.clear()
        elif line.startswith('Content-Disposition:'):
            content_disposition, disp_options = cgi.parse_header(line)
            if'filename' in disp_options:
                context.filename = disp_options.get('filename', 'SyncSend_download')
            else:
                assert content_disposition.split(':')[1].strip() == 'form-data'
                context.form_data_name = disp_options['name']
        elif line.startswith('Content-Type:'):
            # This is a header like:
            # Content-Type: image/jpeg
            context.content_type = line.split(':')[1].strip()
        elif not line:
            # Blank line -- we're going to start receiving raw data after this
            if getattr(context, 'filename', None):
                # We're receiving a file like:
                # --------boundary
                # Content-Disposition: form-data; name="file"; filename="image.jpg"
                # Content-Type: image/jpeg
                self.file_started = True
                self.setRawMode()
                self.request.fileStarted(filename=context.filename, content_type=context.content_type)
            else:
                # We're receiving a form field like:
                # --------boundary
                # Content-Disposition: form-data; name="fieldname"
                self.file_started = False
        else:
            # We're receiving the value of a form field
            assert not self.file_started
            # TODO: can there be multiline form field values?
            self.request.args[context.form_data_name] = line


    def rawDataReceived(self, data):
        """Override this for when raw data is received.
        """
        # TODO: test this for very small chunk sizes and large boundaries
        # TODO: test for different sequences of form-data and files in the multipart form
        # TODO: surely there's a more efficient implementation of this?
        # If end_boundary is N bytes long, we mustn't send the last N bytes we've seen
        # until we know whether they're the end boundary or not
        data = self.previous_chunk + data
        # Save the last N bytes of data
        self.previous_chunk = data[-len(self.end_boundary):]

        # Give the first part of the data to the request
        data = data[:-len(self.end_boundary)]
        if data:
            self.request.handleFileChunk(data)

        if self.previous_chunk == self.end_boundary:
            self.request.fileCompleted()
            self.setLineMode()
            # Break circular reference
#            self.request = None

class FileUploadRequest:
    """
    A HTTP request for uploading files. Copied and adapted from twisted.web.http.Request.

    Many simplifications over Twisted's Request: no cookies, no authentication, no SSL
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
    queued = False
    _disconnected = False

    # OVERRIDABLES
    def fileStarted(self, filename, content_type):
        print 'started', filename

    def handleFileChunk(self, data):
        pass

    def fileCompleted(self):
        print 'done'

    # PUBLIC METHODS
    def pause(self):
        self.channel.pauseProducing()
        if self.formDataReceiver: self.formDataReceiver.pauseProducing()

    def resume(self):
        if self.formDataReceiver: self.formDataReceiver.resumeProducing()
        self.channel.resumeProducing()

    def __init__(self, channel, path, queued):
        """
        @param channel: the channel we're connected to.
        @param path: URI path
        @param queued: are we in the request queue, or can we start writing to
            the transport?
        """
        self.notifications = []
        self.channel = channel
        self.queued = queued
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

        if queued:
            self.transport = StringTransport()
        else:
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
        Called when have finished responding and are no longer queued.
        """
        if self.producer:
            log.err(RuntimeError("Producer was not unregistered for %s" % self.uri))
            self.unregisterProducer()
        self.channel.requestDone(self)
        del self.channel
        for d in self.notifications:
            d.callback(None)
        self.notifications = []

    def noLongerQueued(self):
        """
        Notify the object that it is no longer queued.

        We start writing whatever data we have to the transport, etc.

        This method is not intended for users.
        """
        if not self.queued:
            raise RuntimeError, "noLongerQueued() got called unnecessarily."

        self.queued = 0

        # set transport to real one and send any buffer data
        data = self.transport.getvalue()
        self.transport = self.channel.transport
        if data:
            self.transport.write(data)

        # if we have producer, register it with transport
        if (self.producer is not None) and not self.finished:
            self.transport.registerProducer(self.producer, self.streamingProducer)

        # if we're finished, clean up
        if self.finished:
            self._cleanup()

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

        if self.queued:
            if streaming:
                producer.pauseProducing()
        else:
            self.transport.registerProducer(producer, streaming)
    def unregisterProducer(self):
        """
        Unregister the producer.
        """
        if not self.queued:
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
            self.channel.factory.log(self) # TODO

        self.finished = 1
        if not self.queued:
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
        Override in subclasses.
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
    A receiver for HTTP requests.

    @ivar _transferDecoder: C{None} or an instance of
        L{_ChunkedTransferDecoder} if the request body uses the I{chunked}
        Transfer-Encoding.
    """

    maxHeaders = 500 # max number of headers allowed per request

    length = 0
    __header = ''
    __first_line = 1
    __content = None

    # set in instances or subclasses
    requestFactory = Request

    _savedTimeOut = None
    _receivedHeaderCount = 0

    uploadRequestClass = FileUploadRequest
    downloadRequestClass = FileDownloadRequest

    def __init__(self):
        # the request queue
        self.requests = []
        self._transferDecoder = None


    def connectionMade(self):
        self.setTimeout(self.timeOut)

    def lineReceived(self, line):
        self.resetTimeout()

        if self.__first_line:
            # IE sends an extraneous empty line (\r\n) after a POST request;
            # eat up such a line, but only ONCE
            if not line and self.__first_line == 1:
                self.__first_line = 2
                return

            self.__first_line = 0
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

            self._command = command
            self._path = request
            self._version = version

            # create a new Request object
            if command == 'POST':
                request = self.uploadRequestClass(channel=self, path=request, queued=False)
            else:
                request = self.downloadRequestClass(channel=self, path=request, queued=False)
            self.requests.append(request)
        elif line == '':
            if self.__header:
                self.headerReceived(self.__header)
            self.__header = ''
            self.allHeadersReceived()
            if self.length == 0:
                self.allContentReceived()
            else:
                self.setRawMode()
        elif line[0] in ' \t':
            self.__header = self.__header+'\n'+line
        else:
            if self.__header:
                self.headerReceived(self.__header)
            self.__header = line


    def _finishRequestBody(self, data):
        self.allContentReceived()
        self.setLineMode(data)


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
                self.length, self.requests[-1].handleContentChunk, self._finishRequestBody)
        elif header == 'transfer-encoding' and data.lower() == 'chunked':
            self.length = None
            self._transferDecoder = _ChunkedTransferDecoder(
                self.requests[-1].handleContentChunk, self._finishRequestBody)

        reqHeaders = self.requests[-1].requestHeaders
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
        command = self._command
        path = self._path
        version = self._version

        # reset ALL state variables, so we don't interfere with next request
        self.length = 0
        self._receivedHeaderCount = 0
        self.__first_line = 1
        self._transferDecoder = None
        del self._command, self._path, self._version

        # Disable the idle timeout, in case this request takes a long
        # time to finish generating output.
        if self.timeOut:
            self._savedTimeOut = self.setTimeout(None)

        req = self.requests[-1]
        req.requestReceived(command, path, version)

    def rawDataReceived(self, data):
        self.resetTimeout()
        self._transferDecoder.dataReceived(data)


    def allHeadersReceived(self):
        req = self.requests[-1]
        req.gotLength(self.length)

    def requestDone(self, request):
        """
        Called by first request in queue when it is done.
        """
        if request != self.requests[0]: raise TypeError
        del self.requests[0]
        self.transport.loseConnection()

    def timeoutConnection(self):
        log.msg("Timing out client: %s" % str(self.transport.getPeer()))
        policies.TimeoutMixin.timeoutConnection(self)

    def connectionLost(self, reason):
        self.setTimeout(None)
        for request in self.requests:
            request.connectionLost(reason)
